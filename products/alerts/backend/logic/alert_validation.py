from typing import Any

import posthoganalytics

from posthog.schema import AlertCalculationInterval, NodeKind

from posthog.models import Organization, Team, User

from products.alerts.backend.evaluation.validation import (
    THRESHOLD_BOUNDS_REQUIRED_MESSAGE,
    should_default_check_ongoing_interval,
    validate_alert_config,
    validate_alert_insight_query,
)
from products.alerts.backend.facade.contracts import AlertValidationState, AlertWriteRefused
from products.alerts.backend.facade.evaluation import validate_evaluation_delay
from products.alerts.backend.models.alert import AlertConfiguration


def validate_insight_feature_access(kind: NodeKind | None, *, actor: User, organization: Organization) -> None:
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
    instance: AlertValidationState | None,
    query: dict[str, Any] | None,
    insight_kind: NodeKind | None,
    owner: User | None,
    team: Team,
    organization: Organization,
    actor: User,
) -> dict[str, Any]:
    condition = attrs.get("condition", instance.condition if instance else None)
    config = attrs.get("config", instance.config if instance else None)
    validate_insight_feature_access(insight_kind, actor=actor, organization=organization)
    if query is None:
        raise AlertWriteRefused({"insight": ["Insight has no valid query."]})

    threshold_config = None
    if "threshold" in attrs and isinstance(attrs["threshold"], dict):
        threshold_config = attrs["threshold"].get("configuration")
    elif instance:
        threshold_config = instance.threshold_configuration

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

    try:
        validate_evaluation_delay(query, config, evaluation_delay)
        validate_alert_insight_query(
            query,
            team=team,
            # The alert evaluates as its creator, so an update validates as that user rather
            # than as whoever is editing it.
            user=owner,
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
        if not detector_config and insight_kind != NodeKind.METRICS_QUERY:
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

    # Only a create adds an alert. Turning an existing one on, a takeover included, needs a free slot among
    # the enabled ones.
    if instance is None:
        if msg := AlertConfiguration.check_alert_limit(team.id, organization):
            raise AlertWriteRefused({"alert": [msg]})
    elif attrs.get("enabled") is True and not instance.enabled:
        if msg := AlertConfiguration.enable_limit_error(
            team_id=team.id, organization=organization, exclude_id=str(instance.id)
        ):
            raise AlertWriteRefused({"enabled": [msg]})

    existing_enabled = instance.enabled if instance else True
    if msg := AlertConfiguration.real_time_alert_validation_error(
        team_id=team.id,
        organization=organization,
        calculation_interval=calculation_interval,
        enabled=attrs.get("enabled", existing_enabled) is True,
        existing=AlertConfiguration(
            id=instance.id, enabled=instance.enabled, calculation_interval=instance.calculation_interval
        )
        if instance
        else None,
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
