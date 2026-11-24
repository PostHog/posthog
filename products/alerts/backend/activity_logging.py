"""Activity-log and cleanup receivers for alert configuration changes.

Kept in their own import-light module so the alerts AppConfig can wire them at ready()
without importing the API module — whose module-scope imports reach the alert detector
stack (posthog.tasks.alerts -> numpy). The Temporal/celery alert-check paths mutate these
models directly, so the receivers must connect in every process, not just where the API
loads.
"""

import dataclasses
from collections.abc import Collection, Mapping
from typing import Literal, Optional
from uuid import UUID

from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

from posthog.models.activity_logging.activity_log import (
    ActivityContextBase,
    Change,
    Detail,
    changes_between,
    log_activity,
)
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.user import User

from products.alerts.backend.models.alert import AlertConfiguration, AlertSubscription, Threshold
from products.cdp.backend.facade.models import HogFunction


@dataclasses.dataclass(frozen=True)
class AlertConfigurationContext(ActivityContextBase):
    insight_id: Optional[int] = None
    insight_short_id: Optional[str] = None
    insight_name: Optional[str] = "Insight"
    alert_id: Optional[int] = None
    alert_name: Optional[str] = "Alert"


@dataclasses.dataclass(frozen=True)
class AlertSubscriptionContext(AlertConfigurationContext):
    subscriber_name: Optional[str] = None
    subscriber_email: Optional[str] = None


@mutable_receiver(model_activity_signal, sender=AlertConfiguration)
def handle_alert_configuration_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
) -> None:
    _log_alert_configuration_change(
        before_update, after_update, activity=activity, user=user, was_impersonated=was_impersonated
    )


def _log_alert_configuration_change(
    before: AlertConfiguration | None,
    after: AlertConfiguration,
    *,
    activity: str,
    user: User | None,
    was_impersonated: bool,
    changes: list[Change] | None = None,
) -> None:
    log_activity(
        organization_id=after.team.organization_id,
        team_id=after.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=after.id,
        scope="AlertConfiguration",
        activity=activity,
        detail=Detail(
            changes=changes
            if changes is not None
            else changes_between("AlertConfiguration", previous=before, current=after),
            name=after.name or f"Alert for {after.insight.name}",
            context=AlertConfigurationContext(
                insight_id=after.insight_id,
                insight_short_id=after.insight.short_id,
                insight_name=after.insight.name,
            ),
        ),
    )


def log_platform_alert_edit(
    before: AlertConfiguration, after: AlertConfiguration, *, user: User | None, was_impersonated: bool
) -> None:
    """Logs an edit of a moved alert, which writes only its platform copy, so the row's receivers never
    see it. Writes the entries a row save writes, one for the alert's fields and one for its threshold, so
    the alert's history stays on the scope and id it started under."""
    changes = changes_between("AlertConfiguration", previous=before, current=after)
    if changes:
        _log_alert_configuration_change(
            before, after, activity="updated", user=user, was_impersonated=was_impersonated, changes=changes
        )
    threshold_before, threshold_after = before.threshold, after.threshold
    if threshold_before is None or threshold_after is None:
        return
    threshold_changes = changes_between("Threshold", previous=threshold_before, current=threshold_after)
    if threshold_changes:
        _log_threshold_change(
            after, threshold_changes, activity="updated", user=user, was_impersonated=was_impersonated
        )


@mutable_receiver(model_activity_signal, sender=Threshold)
def handle_threshold_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
) -> None:
    alert_config = None
    if hasattr(after_update, "alertconfiguration_set"):
        alert_config = after_update.alertconfiguration_set.first()

    if alert_config:
        _log_threshold_change(
            alert_config,
            changes_between("Threshold", previous=before_update, current=after_update),
            activity=activity,
            user=user,
            was_impersonated=was_impersonated,
        )


def _log_threshold_change(
    alert_config: AlertConfiguration,
    changes: list[Change],
    *,
    activity: str,
    user: User | None,
    was_impersonated: bool,
) -> None:
    log_activity(
        organization_id=alert_config.team.organization_id,
        team_id=alert_config.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=alert_config.id,
        scope="AlertConfiguration",
        activity=activity,
        detail=Detail(
            changes=changes,
            type="threshold_change",
            context=AlertConfigurationContext(
                insight_id=alert_config.insight_id,
                insight_short_id=alert_config.insight.short_id,
                insight_name=alert_config.insight.name,
                alert_name=alert_config.name,
            ),
        ),
    )


@mutable_receiver(model_activity_signal, sender=AlertSubscription)
def handle_alert_subscription_change(
    before_update, after_update, activity, user, was_impersonated=False, **kwargs
) -> None:
    alert_config = after_update.alert_configuration

    if alert_config:
        log_activity(
            organization_id=alert_config.team.organization_id,
            team_id=alert_config.team_id,
            user=user,
            was_impersonated=was_impersonated,
            item_id=alert_config.id,
            scope="AlertConfiguration",
            activity=activity,
            detail=Detail(
                changes=changes_between("AlertSubscription", previous=before_update, current=after_update),
                type="alert_subscription_change",
                context=AlertSubscriptionContext(
                    insight_id=alert_config.insight_id,
                    insight_short_id=alert_config.insight.short_id,
                    insight_name=alert_config.insight.name,
                    subscriber_name=after_update.user.get_full_name(),
                    subscriber_email=after_update.user.email,
                    alert_name=alert_config.name,
                ),
            ),
        )


def log_native_subscriber_changes(
    alert: AlertConfiguration,
    *,
    actor: User | None,
    was_impersonated: bool,
    added: Collection[int],
    removed: Collection[int],
) -> None:
    """The entries `handle_alert_subscription_change` and `handle_alert_subscription_delete` write, for an
    alert with no insight row, whose subscribers have no `AlertSubscription` rows to send the signals."""
    for user in User.objects.filter(id__in=[*added, *removed]).order_by("id"):
        log_activity(
            organization_id=alert.team.organization_id,
            team_id=alert.team_id,
            user=actor,
            was_impersonated=was_impersonated,
            item_id=alert.id,
            scope="AlertConfiguration",
            activity="created" if user.id in added else "deleted",
            detail=Detail(
                type="alert_subscription_change",
                context=AlertSubscriptionContext(
                    insight_id=alert.insight_id,
                    insight_short_id=alert.insight.short_id,
                    insight_name=alert.insight.name,
                    subscriber_name=user.get_full_name(),
                    subscriber_email=user.email,
                    alert_name=alert.name,
                ),
            ),
        )


def log_destination_changes(
    *,
    team_id: int,
    alert_id: UUID,
    actor_id: int,
    was_impersonated: bool,
    action: Literal["created", "deleted"],
    destination_types: Mapping[UUID, str | None],
) -> None:
    """Logs destinations added to or removed from an insight alert, with or without an insight row. Each
    one is named by id and type only, because its settings hold webhook URLs and routing keys."""
    # Deferred to keep this module import-light, because `ready()` imports it in every process.
    from products.alerts.backend.platform_insight_alert import native_insight_alert_view  # noqa: PLC0415

    if not destination_types:
        return
    alert = AlertConfiguration.objects.select_related("insight", "team").filter(team_id=team_id, id=alert_id).first()
    if alert is None and (view := native_insight_alert_view(team_id, alert_id)) is not None:
        alert = AlertConfiguration.from_platform_view(view, team_id=team_id)
    if alert is None:
        return
    log_activity(
        organization_id=alert.team.organization_id,
        team_id=alert.team_id,
        user=User.objects.filter(id=actor_id).first(),
        was_impersonated=was_impersonated,
        item_id=alert.id,
        scope="AlertConfiguration",
        activity="updated",
        detail=Detail(
            name=alert.name,
            type="alert_destination_change",
            changes=[
                Change(
                    type="AlertConfiguration",
                    action=action,
                    field="destinations",
                    before=summary if action == "deleted" else None,
                    after=summary if action == "created" else None,
                )
                for summary in (
                    {"id": str(destination_id), "type": destination_type}
                    for destination_id, destination_type in sorted(destination_types.items(), key=lambda i: str(i[0]))
                )
            ],
            context=AlertConfigurationContext(
                insight_id=alert.insight_id,
                insight_short_id=alert.insight.short_id,
                insight_name=alert.insight.name,
                alert_name=alert.name,
            ),
        ),
    )


@receiver(pre_delete, sender=AlertConfiguration)
def delete_platform_shadow_copy(sender, instance: AlertConfiguration, **kwargs) -> None:
    # A copy the platform owns is left to `delete_alert_destinations_and_copy`, which ends its firings first.
    if instance.platform_owned:
        return
    from products.alerts.backend.platform_ownership import delete_shadow_alert_copy

    delete_shadow_alert_copy(team_id=instance.team_id, alert_id=instance.id)


@receiver(pre_delete, sender=AlertSubscription)
def handle_alert_subscription_delete(sender, instance, **kwargs) -> None:
    from posthog.models.activity_logging.model_activity import get_current_user, get_was_impersonated

    alert_config = instance.alert_configuration

    if alert_config:
        log_activity(
            organization_id=alert_config.team.organization_id,
            team_id=alert_config.team_id,
            user=get_current_user(),
            was_impersonated=get_was_impersonated(),
            item_id=alert_config.id,
            scope="AlertConfiguration",
            activity="deleted",
            detail=Detail(
                type="alert_subscription_change",
                context=AlertSubscriptionContext(
                    insight_id=alert_config.insight_id,
                    insight_short_id=alert_config.insight.short_id,
                    insight_name=alert_config.insight.name,
                    subscriber_name=instance.user.get_full_name(),
                    subscriber_email=instance.user.email,
                    alert_name=alert_config.name,
                ),
            ),
        )


@receiver(post_save, sender=HogFunction)
def delete_copying_destination_rows(sender, instance: HogFunction, **kwargs) -> None:
    # A destination deleted through the generic HogFunction API, Terraform or MCP must take its platform row
    # with it, or the row stops being skipped and keeps sending. A bulk `.update()` does not reach here, which
    # is how a conversion that deliberately keeps the row retires the HogFunctions.
    if not instance.deleted:
        return
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "deleted" not in update_fields:
        return
    from products.alerts_platform.backend.facade.api import delete_rows_copying

    delete_rows_copying(team_id=instance.team_id, hog_function_ids=[instance.id])
