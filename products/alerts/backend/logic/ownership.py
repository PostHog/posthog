from copy import deepcopy
from typing import Any
from uuid import UUID

from django.db import DatabaseError, transaction
from django.utils import timezone

from posthog.api.query_access_check import denied_query_resources
from posthog.constants import AvailableFeature
from posthog.dataclasses import frozen
from posthog.event_usage import AnalyticsProps
from posthog.exceptions_capture import capture_exception
from posthog.models import User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.activity_logging.model_activity import ActingUserContext
from posthog.query_creator_access import CreatorLeftOrganizationError, assert_creator_can_run
from posthog.schema_migrations.upgrade_manager import upgrade_insight

from products.access_control.backend.facade.user_access_control import UserAccessControl, UserAccessControlError
from products.alerts.backend.activity_logging import AlertConfigurationContext
from products.alerts.backend.facade.contracts import AlertInsightSnapshot, AlertWriteRefused, PlatformCannotOwn
from products.alerts.backend.facade.platform import follow_insight_alert
from products.alerts.backend.insight_alert_state_machine import apply_enable, apply_threshold_change
from products.alerts.backend.llm_detector_limits import (
    LLMAlertRefusal,
    LLMAlertWrite,
    is_llm_detector_config,
    llm_detector_access_error,
    prepare_llm_alert_write,
)
from products.alerts.backend.logic.alert_validation import validate_alert_write
from products.alerts.backend.models.alert import AlertConfiguration, Threshold
from products.alerts.backend.platform_insight_alert import (
    enable_native_insight_alert,
    moved_alert_settings,
    native_insight_alert_view,
)
from products.alerts.backend.platform_ownership import write_moved_alert_edit
from products.alerts.backend.platform_subscribers import sync_alert_subscriber_destinations
from products.alerts_platform.backend.facade.api import assign_native_creator, lock_source_configuration
from products.alerts_platform.backend.facade.contracts import (
    InvalidPlatformAlertEdit,
    PlatformAlertCreateRefused,
    SourceKind,
)
from products.product_analytics.backend.facade.api import lock_insight_for_evaluation


@frozen
class OwnershipSnapshot:
    """Validation inputs only: evaluation progress must not invalidate an ownership change."""

    fields: dict[str, Any]
    threshold: dict[str, Any] | None
    query: dict[str, Any] | None
    filters: dict[str, Any] | None
    insight_deleted: bool

    @classmethod
    def of(cls, alert: AlertConfiguration) -> "OwnershipSnapshot":
        return cls(
            fields=deepcopy(
                {
                    field: getattr(alert, field)
                    for field in (
                        "insight_id",
                        "created_by_id",
                        "owner",
                        "enabled",
                        "condition",
                        "config",
                        "detector_config",
                        "calculation_interval",
                        "evaluation_delay_intervals",
                        "investigation_agent_enabled",
                        "investigation_gates_notifications",
                    )
                }
            ),
            threshold=deepcopy(alert.threshold.configuration if alert.threshold else None),
            query=deepcopy(alert.insight.query),
            filters=deepcopy(alert.insight.filters),
            insight_deleted=alert.insight.deleted,
        )


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
        if lock:
            lock_source_configuration(team_id=team_id, public_id=alert_id)
        settings = moved_alert_settings(team_id=team_id, alert_ids=[alert_id]).get(alert_id)
        if settings is None:
            raise AlertConfiguration.DoesNotExist
        for field, value in settings.fields.items():
            setattr(alert, field, value)
        alert.schedule_start_time = settings.schedule_start_time
        if settings.threshold is None:
            alert.threshold = None
        elif alert.threshold is None:
            alert.threshold = Threshold(team_id=team_id, insight=alert.insight, configuration=settings.threshold)
        else:
            alert.threshold.configuration = settings.threshold
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
    try:
        assert_creator_can_run(owner, alert.team, alert.insight)
    except (CreatorLeftOrganizationError, UserAccessControlError) as error:
        subject = "you don't" if owner.pk == actor.pk else "the new owner doesn't"
        raise AlertWriteRefused(f"Can't take ownership: {subject} have access to this insight.") from error
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
        if locked.platform_owned and locked.threshold:
            locked.threshold.created_by = locked.threshold.created_by or actor
            locked.threshold.save()
        locked.save()
        if locked.platform_owned:
            write_moved_alert_edit(
                team_id=team_id,
                alert_id=alert_id,
                snooze_changed=False,
                rescheduled=enable_now or "config" in attrs,
            )
        sync_alert_subscriber_destinations(team_id=team_id, alert_id=alert_id)
        if enable_now and not locked.platform_owned:
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
    expected_insight: AlertInsightSnapshot | None = None,
) -> AlertConfiguration:
    alert = _load_alert(team_id, alert_id)
    snapshot = OwnershipSnapshot.of(alert)
    if expected_insight is not None:
        with upgrade_insight(alert.insight):
            if (alert.insight_id, alert.insight.query, alert.insight.filters) != (
                expected_insight.id,
                expected_insight.query,
                expected_insight.filters,
            ):
                raise AlertWriteRefused("The alert or insight changed. Retry the ownership transfer.", status_code=409)
    _validate_owner(alert, actor, owner)
    alert.created_by = owner
    attrs = validate_alert_write(
        {"enabled": True}, instance=alert, team=alert.team, organization=alert.team.organization, actor=actor
    )
    admission = prepare_llm_alert_write(
        LLMAlertWrite(
            team_id=team_id,
            organization=alert.team.organization,
            principal=owner,
            detector_config=alert.detector_config,
            enabled=True,
            calculation_interval=alert.calculation_interval,
            existing=alert,
        )
    )
    if isinstance(admission, LLMAlertRefusal):
        raise AlertWriteRefused({admission.field: [admission.message]} if admission.field else admission.message)

    with transaction.atomic(), ActingUserContext(actor):
        if not lock_insight_for_evaluation(team_id=team_id, insight_id=alert.insight_id):
            raise AlertWriteRefused("The insight no longer exists. Refresh the alert.", status_code=409)
        locked = _load_alert(team_id, alert_id, lock=True)
        if OwnershipSnapshot.of(locked) != snapshot:
            raise AlertWriteRefused("The alert or insight changed. Retry the ownership transfer.", status_code=409)
        if refusal := admission.check_capacity():
            raise AlertWriteRefused({refusal.field: [refusal.message]} if refusal.field else refusal.message)
        previous_owner = locked.created_by
        previous = AlertConfiguration(
            id=locked.id, enabled=locked.enabled, calculation_interval=locked.calculation_interval
        )
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
