from typing import Any
from uuid import UUID

from django.db import DatabaseError, transaction
from django.utils import timezone

from posthog.schema import NodeKind

from posthog.api.query_access_check import denied_query_resources
from posthog.constants import AvailableFeature
from posthog.event_usage import AnalyticsProps
from posthog.exceptions_capture import capture_exception
from posthog.models import User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.activity_logging.model_activity import ActingUserContext
from posthog.query_creator_access import CreatorLeftOrganizationError, assert_creator_can_run
from posthog.schema_migrations.upgrade_manager import upgrade_insight

from products.access_control.backend.facade.user_access_control import UserAccessControl, UserAccessControlError
from products.alerts.backend.activity_logging import AlertConfigurationContext
from products.alerts.backend.facade.contracts import AlertWriteRefused, PlatformCannotOwn
from products.alerts.backend.facade.platform import follow_insight_alert
from products.alerts.backend.insight_alert_state_machine import apply_enable, apply_threshold_change
from products.alerts.backend.llm_detector_limits import (
    LLMAlertWrite,
    admit_llm_alert_write,
    is_llm_detector_config,
    llm_detector_access_error,
)
from products.alerts.backend.logic.alert_validation import validate_alert_write
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.platform_insight_alert import (
    enable_native_insight_alert,
    native_insight_alert_view,
    show_copy_settings,
)
from products.alerts.backend.platform_ownership import on_updated, show_locked_copy
from products.alerts.backend.platform_subscribers import sync_alert_subscriber_destinations
from products.alerts_platform.backend.facade.api import assign_native_creator
from products.alerts_platform.backend.facade.contracts import (
    InvalidPlatformAlertEdit,
    PlatformAlertCreateRefused,
    SourceKind,
)
from products.product_analytics.backend.facade.api import lock_insight_for_evaluation


def _load_alert(team_id: int, alert_id: UUID, *, lock: bool = False) -> AlertConfiguration:
    rows = AlertConfiguration.objects.select_related("team__organization", "insight", "created_by", "threshold")
    if lock:
        rows = rows.select_for_update(of=("self",), no_key=True)
    alert = rows.filter(team_id=team_id, id=alert_id).first()
    if alert is None:
        view = native_insight_alert_view(team_id, alert_id, lock=lock)
        alert = AlertConfiguration.from_platform_view(view, team_id=team_id) if view else None
        if alert is None:
            raise AlertConfiguration.DoesNotExist
    elif alert.platform_owned:
        shown = show_locked_copy(alert) if lock else alert.id in show_copy_settings([alert])
        if not shown:
            raise AlertConfiguration.DoesNotExist
    return alert


def _validate_owner(alert: AlertConfiguration, actor: User, owner: User) -> None:
    access = UserAccessControl(user=actor, team=alert.team)
    if owner.pk != actor.pk and not access.is_organization_admin:
        raise AlertWriteRefused(
            "Only an organization admin can assign an alert to another person. "
            "Take ownership yourself or ask an admin to transfer it.",
            status_code=403,
        )
    try:
        assert_creator_can_run(actor, alert.team, alert.insight)
        if not access.check_access_level_for_resource("alert", "editor"):
            raise AlertWriteRefused("You need permission to edit alerts.", status_code=403)
    except (CreatorLeftOrganizationError, UserAccessControlError) as error:
        raise AlertWriteRefused(
            "You need access to this insight to change its alert's owner.", status_code=403
        ) from error
    if owner.pk != actor.pk:
        try:
            assert_creator_can_run(owner, alert.team, alert.insight)
        except (CreatorLeftOrganizationError, UserAccessControlError) as error:
            raise AlertWriteRefused(
                "Can't take ownership: the new owner doesn't have access to this insight."
            ) from error
    if is_llm_detector_config(alert.detector_config):
        if access_error := llm_detector_access_error(
            distinct_id=str(owner.distinct_id), organization=alert.team.organization
        ):
            raise AlertWriteRefused(access_error)
    if alert.insight.deleted:
        raise AlertWriteRefused({"insight": ["This insight was deleted. Pick another insight."]})
    _validate_query_access(alert, actor, owner)


def _validate_query_access(alert: AlertConfiguration, actor: User, owner: User) -> None:
    with upgrade_insight(alert.insight):
        query = alert.insight.query
    if query is None:
        return
    try:
        with transaction.atomic():
            denied = denied_query_resources(
                owner,
                alert.team,
                [query],
                check_table_access=alert.team.organization.is_feature_available(AvailableFeature.ACCESS_CONTROL),
            )
    except DatabaseError as error:
        capture_exception(error)
        raise AlertWriteRefused(
            "Couldn't check access for this ownership change. Try again.",
            code="ownership_access_check_unavailable",
            status_code=503,
        ) from error
    if denied:
        names = ", ".join(f"`{name}`" for name in denied)
        subject = "You need" if owner.pk == actor.pk else "The new owner needs"
        action = "take ownership of" if owner.pk == actor.pk else "transfer"
        raise AlertWriteRefused(f"{subject} access to {names} to {action} this alert.")


def _record_transfer(
    alert: AlertConfiguration, actor: User, owner: User, previous_owner: User | None, was_impersonated: bool
) -> None:
    log_activity(
        organization_id=alert.team.organization_id,
        team_id=alert.team_id,
        user=actor,
        was_impersonated=was_impersonated,
        item_id=alert.id,
        scope="AlertConfiguration",
        activity="took_ownership" if owner.pk == actor.pk else "transferred_ownership",
        detail=Detail(
            name=alert.name or f"Alert for {alert.insight.name}",
            changes=[
                Change(
                    type="AlertConfiguration",
                    action="changed",
                    field="created_by",
                    before={"id": previous_owner.id, "email": previous_owner.email} if previous_owner else None,
                    after={"id": owner.id, "email": owner.email},
                )
            ],
            context=AlertConfigurationContext(
                insight_id=alert.insight_id, insight_short_id=alert.insight.short_id, insight_name=alert.insight.name
            ),
        ),
    )


def _save_owner_and_enable(
    locked: AlertConfiguration, owner: User, actor: User, attrs: dict[str, Any]
) -> AlertConfiguration:
    team_id, alert_id = locked.team_id, locked.id
    if locked.has_no_insight_row:
        if not assign_native_creator(
            team_id=team_id,
            source_kinds=[SourceKind.INSIGHT.value],
            configuration_id=alert_id,
            created_by_id=owner.id,
        ):
            raise AlertConfiguration.DoesNotExist
        view = enable_native_insight_alert(team_id=team_id, alert_id=alert_id)
        updated = AlertConfiguration.from_platform_view(view, team_id=team_id) if view else None
        if updated is None:
            raise AlertConfiguration.DoesNotExist
    elif locked.platform_owned:
        enable_now = not locked.enabled
        locked.enabled = True
        if "config" in attrs:
            locked.config = attrs["config"]
        locked.created_by = owner
        locked.next_check_at = timezone.now()
        on_updated(locked, snooze_changed=False, rescheduled=enable_now or "config" in attrs)
        sync_alert_subscriber_destinations(team_id=team_id, alert_id=alert_id)
        updated = locked
    else:
        enable_now = not locked.enabled
        if enable_now:
            apply_enable(locked)
            locked.next_check_at = timezone.now()
        if "config" in attrs and attrs["config"] != locked.config:
            locked.config = attrs["config"]
            apply_threshold_change(locked)
            locked.next_check_at = timezone.now()
        locked.created_by = owner
        locked.save()
        sync_alert_subscriber_destinations(team_id=team_id, alert_id=alert_id)
        if enable_now:
            transaction.on_commit(lambda: follow_insight_alert(team_id=team_id, alert_id=alert_id), robust=True)
        updated = locked
    return updated


def take_alert_ownership(
    *,
    team_id: int,
    alert_id: UUID,
    actor: User,
    owner: User,
    was_impersonated: bool,
    analytics_props: AnalyticsProps | None = None,
    has_metrics_scope: bool = True,
) -> AlertConfiguration:
    insight_id = _load_alert(team_id, alert_id).insight_id
    with transaction.atomic(), ActingUserContext(actor):
        if not lock_insight_for_evaluation(team_id=team_id, insight_id=insight_id):
            raise AlertWriteRefused("The insight no longer exists. Refresh the alert.", status_code=409)
        locked = _load_alert(team_id, alert_id, lock=True)
        if locked.insight_id != insight_id:
            raise AlertWriteRefused("The alert's insight changed. Retry the ownership transfer.", status_code=409)
        if not has_metrics_scope and locked.insight.alertable_query_kind == NodeKind.METRICS_QUERY:
            raise AlertWriteRefused(
                "API key missing required scope 'metrics:read'", code="metrics_scope_required", status_code=403
            )
        _validate_owner(locked, actor, owner)
        previous_owner = locked.created_by
        previous = AlertConfiguration(
            id=locked.id, enabled=locked.enabled, calculation_interval=locked.calculation_interval
        )
        locked.created_by = owner
        with upgrade_insight(locked.insight):
            attrs = validate_alert_write(
                {"enabled": True},
                instance=locked.validation_state(),
                query=locked.insight.query,
                insight_kind=locked.insight.alertable_query_kind,
                team=locked.team,
                organization=locked.team.organization,
                actor=actor,
                owner=owner,
            )
        refusal = admit_llm_alert_write(
            LLMAlertWrite(
                team_id=team_id,
                organization=locked.team.organization,
                principal=owner,
                detector_config=locked.detector_config,
                enabled=True,
                calculation_interval=locked.calculation_interval,
                existing=locked,
            )
        )
        if refusal:
            raise AlertWriteRefused({refusal.field: [refusal.message]} if refusal.field else refusal.message)
        try:
            updated = _save_owner_and_enable(locked, owner, actor, attrs)
        except InvalidPlatformAlertEdit as error:
            raise AlertWriteRefused({error.field_name: str(error)}) from error
        except (PlatformCannotOwn, PlatformAlertCreateRefused) as error:
            raise AlertWriteRefused(str(error)) from error
        if limit_error := AlertConfiguration.update_limit_error(
            team_id=team_id,
            organization=updated.team.organization,
            calculation_interval=updated.calculation_interval,
            enabled=True,
            existing=previous,
        ):
            raise AlertWriteRefused({"calculation_interval": [limit_error]})
        if not updated.has_no_insight_row:
            updated.report_updated(actor, analytics_props=analytics_props)
        _record_transfer(updated, actor, owner, previous_owner, was_impersonated)
    return updated
