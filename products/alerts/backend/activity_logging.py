"""Activity-log and cleanup receivers for alert configuration changes.

Kept in their own import-light module so the alerts AppConfig can wire them at ready()
without importing the API module — whose module-scope imports reach the alert detector
stack (posthog.tasks.alerts -> numpy). The Temporal/celery alert-check paths mutate these
models directly, so the receivers must connect in every process, not just where the API
loads.
"""

import dataclasses
from typing import Optional

from django.db.models.signals import pre_delete
from django.dispatch import receiver

from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver

from products.alerts.backend.models.alert import AlertConfiguration, AlertSubscription, Threshold


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
    log_activity(
        organization_id=after_update.team.organization_id,
        team_id=after_update.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=after_update.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=after_update.name or f"Alert for {after_update.insight.name}",
            context=AlertConfigurationContext(
                insight_id=after_update.insight_id,
                insight_short_id=after_update.insight.short_id,
                insight_name=after_update.insight.name,
            ),
        ),
    )


@mutable_receiver(model_activity_signal, sender=Threshold)
def handle_threshold_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
) -> None:
    alert_config = None
    if hasattr(after_update, "alertconfiguration_set"):
        alert_config = after_update.alertconfiguration_set.first()

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
                changes=changes_between("Threshold", previous=before_update, current=after_update),
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


@receiver(pre_delete, sender=AlertConfiguration)
def cleanup_alert_hog_functions(sender, instance: AlertConfiguration, **kwargs) -> None:
    from products.cdp.backend.models.hog_functions.hog_function import HogFunction, HogFunctionType

    for hog_function in HogFunction.objects.filter(
        team_id=instance.team_id,
        type=HogFunctionType.INTERNAL_DESTINATION,
        deleted=False,
        filters__contains={"properties": [{"key": "alert_id", "value": str(instance.id)}]},
    ):
        hog_function.enabled = False
        hog_function.deleted = True
        hog_function.save()


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
