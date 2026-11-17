from typing import Any

import posthoganalytics

from posthog.schema import AlertCalculationInterval, NodeKind

from posthog.models import Organization, Team, User
from posthog.query_creator_access import (
    CreatorLeftOrganizationError,
    assert_creator_can_run,
    describe_owner_unavailable,
    owner_unavailable_code,
)
from posthog.schema_migrations.upgrade_manager import upgrade_insight

from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.alerts.backend.evaluation.validation import (
    THRESHOLD_BOUNDS_REQUIRED_MESSAGE,
    should_default_check_ongoing_interval,
    validate_alert_config,
    validate_alert_insight_query,
)
from products.alerts.backend.facade.contracts import AlertWriteRefused
from products.alerts.backend.facade.evaluation import validate_evaluation_delay
from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.facade.models import Insight


def validate_insight_feature_access(insight: Insight, *, actor: User, organization: Organization) -> None:
    kind = insight.alertable_query_kind
    if kind is None:
        raise AlertWriteRefused("Alerts are not supported for this insight.")
    if kind == NodeKind.METRICS_QUERY and not posthoganalytics.feature_enabled(
        "metrics", str(actor.distinct_id), groups={"organization": str(organization.id)}
    ):
        raise AlertWriteRefused("Metrics insight alerts are not enabled for your account.")


def validate_interval_entitlement(
    *, calculation_interval: str | AlertCalculationInterval | None, organization: Organization
) -> None:
    if error := AlertConfiguration.interval_entitlement_error(
        calculation_interval=calculation_interval, organization=organization
    ):
        raise AlertWriteRefused({"calculation_interval": [error]})


def validate_alert_write(
    attrs: dict[str, Any],
    *,
    instance: AlertConfiguration | None,
    team: Team,
    organization: Organization,
    actor: User,
) -> dict[str, Any]:
    if attrs.get("insight") and attrs["insight"].team.id != team.id:
        raise AlertWriteRefused({"insight": ["This insight does not belong to your team."]})

    condition = attrs.get("condition", instance.condition if instance else None)
    config = attrs.get("config", instance.config if instance else None)
    insight = attrs.get("insight") or (instance.insight if instance else None)
    if insight is None:
        raise AlertWriteRefused({"insight": ["Insight is required."]})
    # Checks run as the owner, so an owner who cannot run them would only get the alert disabled again.
    if instance is not None and attrs.get("enabled") is True and not instance.enabled:
        try:
            assert_creator_can_run(instance.created_by, instance.team, insight)
        except (CreatorLeftOrganizationError, UserAccessControlError) as error:
            raise AlertWriteRefused(
                {"enabled": [f"Can't enable this alert. {describe_owner_unavailable(instance.created_by, error)}"]},
                code=owner_unavailable_code(error),
            )
    # Check the effective insight on every write, including an edit that omits the insight field.
    validate_insight_feature_access(insight, actor=actor, organization=organization)
    with upgrade_insight(insight):
        query = insight.query
        if query is None:
            raise AlertWriteRefused({"insight": ["Insight has no valid query."]})

    threshold_config = None
    if "threshold" in attrs and isinstance(attrs["threshold"], dict):
        threshold_config = attrs["threshold"].get("configuration")
    elif instance and instance.threshold:
        threshold_config = instance.threshold.configuration

    calculation_interval = attrs.get(
        "calculation_interval",
        instance.calculation_interval if instance else AlertCalculationInterval.DAILY,
    )

    if "detector_config" in attrs:
        detector_config = attrs["detector_config"]
    elif instance is not None:
        detector_config = instance.detector_config
    else:
        detector_config = None

    require_threshold_bounds = detector_config is None and (
        instance is None or "threshold" in attrs or "detector_config" in attrs
    )

    # Mirror the UI's default for cadences finer than the insight interval. Applied before
    # validate_alert_config so the validated config is the persisted config.
    evaluation_delay = attrs.get("evaluation_delay_intervals", instance.evaluation_delay_intervals if instance else 0)
    if not evaluation_delay and isinstance(config, dict) and config.get("check_ongoing_interval") is None:
        if should_default_check_ongoing_interval(
            query=query,
            config=config,
            condition=condition,
            threshold_config=threshold_config,
            calculation_interval=calculation_interval,
        ):
            config = {**config, "check_ongoing_interval": True}
            attrs["config"] = config

    request_user = actor
    creating_user = request_user if isinstance(request_user, User) else None
    try:
        validate_evaluation_delay(query, config, evaluation_delay)
        validate_alert_insight_query(
            query,
            team=team,
            # The alert evaluates as its creator, so an update validates as that user rather
            # than as whoever is editing it.
            user=instance.created_by if instance is not None else creating_user,
        )
        validate_alert_config(
            query,
            condition,
            config,
            threshold_config,
            calculation_interval,
            detector_config=detector_config,
            require_threshold_bounds=require_threshold_bounds,
        )
    except ValueError as e:
        if str(e) == THRESHOLD_BOUNDS_REQUIRED_MESSAGE:
            raise AlertWriteRefused({"threshold": {"configuration": [THRESHOLD_BOUNDS_REQUIRED_MESSAGE]}})
        raise AlertWriteRefused(str(e))

    # The AI detector's own rules (rollout, consent, cadence, cap) run in create/update
    # through admit_llm_alert_write, under the locks they need.
    validate_interval_entitlement(
        calculation_interval=calculation_interval,
        organization=organization,
    )

    # Investigation agent is supported for detector-based alerts (the agent
    # workflow) and for metrics threshold alerts (a synchronous facade
    # investigation attached to the firing check) — nothing else.
    investigation_enabled = attrs.get(
        "investigation_agent_enabled",
        instance.investigation_agent_enabled if instance else False,
    )
    if investigation_enabled:
        detector_config = attrs.get(
            "detector_config",
            instance.detector_config if instance else None,
        )
        if not detector_config and insight.alertable_query_kind != NodeKind.METRICS_QUERY:
            raise AlertWriteRefused(
                {"investigation_agent_enabled": ["Investigation agent is only supported for anomaly detection alerts."]}
            )

    # Notification gating only makes sense when the investigation agent is on —
    # otherwise there's no verdict to wait for and the safety-net task would
    # end up being the only notifier, which defeats the feature.
    gates_notifications = attrs.get(
        "investigation_gates_notifications",
        instance.investigation_gates_notifications if instance else False,
    )
    if gates_notifications and not investigation_enabled:
        raise AlertWriteRefused(
            {"investigation_gates_notifications": ["Notification gating requires investigation_agent_enabled=true."]}
        )

    # Only a create adds an alert; a takeover is a POST that enables an existing one.
    if instance is None:
        if msg := AlertConfiguration.check_alert_limit(team.id, organization):
            raise AlertWriteRefused({"alert": [msg]})

    existing_enabled = instance.enabled if instance else True
    if msg := AlertConfiguration.real_time_alert_validation_error(
        team_id=team.id,
        organization=organization,
        calculation_interval=calculation_interval,
        enabled=attrs.get("enabled", existing_enabled) is True,
        existing=instance,
    ):
        posthoganalytics.capture(
            distinct_id=str(actor.distinct_id),
            event="real time alert limit reached",
            properties={
                "team_id": team.id,
                "organization_id": str(organization.id),
            },
            groups={"organization": str(organization.id)},
        )
        raise AlertWriteRefused({"calculation_interval": [msg]})

    return attrs
