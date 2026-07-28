"""
Built-in autoresearch prediction templates.

Each template resolves to the same pipeline config shape as a custom pipeline,
so validation and creation work identically whether the user started from a template
or built a fully custom definition.

Population specs use a semantic format compiled to HogQL by the training/inference
harness. Supported kinds:
  performed_event_within_days   users who did `event` in the last `days` days
  person_first_seen_within_days users whose first_seen date is within `days` days
  active_not_performed_target   active users (any event in `active_within_days`) who
                                have NOT performed `event`
  ever_performed_event          users who have performed `event` at least once
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import structlog

from posthog.schema import HogQLQuery

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)

# Checked in this order when resolving an activity event for universal templates
_PREFERRED_ACTIVITY_EVENTS = ["$pageview", "$screen", "$autocapture"]

# Internal / noisy events that should never be chosen as the activity signal
_NOISY_EVENTS: frozenset[str] = frozenset(
    {
        "$feature_flag_called",
        "$decide",
        "$set",
        "$identify",
        "$rageclick",
        "$$heatmap",
        "$web_vitals",
        "$exception",
        "$pageview_autocapture",
        "$$plugin_metrics",
    }
)


@dataclass
class AutoresearchTemplate:
    key: str
    display_name: str
    description: str
    default_horizon_days: int
    output_property_prefix: str
    requires_user_event: bool  # user must supply target_event override
    requires_activity_resolution: bool  # target_event resolved from schema
    training_population_spec: dict[str, Any]
    inference_population_spec: dict[str, Any]
    notes: str = ""


TEMPLATES: dict[str, AutoresearchTemplate] = {
    "likely_active_soon": AutoresearchTemplate(
        key="likely_active_soon",
        display_name="Likely active soon",
        description=(
            "Predict which active users will be active again in the next 7 days. "
            "Best universal starter template — works for any product with pageview or session data."
        ),
        default_horizon_days=7,
        output_property_prefix="predicted_p_active_soon",
        requires_user_event=False,
        requires_activity_resolution=True,
        training_population_spec={"kind": "performed_event_within_days", "days": 30},
        inference_population_spec={"kind": "performed_event_within_days", "days": 30},
        notes=(
            "Activity event is resolved from your event schema — prefers $pageview, $screen, "
            "then any high-volume identified-user event. You can override the resolved event."
        ),
    ),
    "at_risk_of_inactivity": AutoresearchTemplate(
        key="at_risk_of_inactivity",
        display_name="At risk of inactivity",
        description=(
            "Identify users unlikely to be active in the next 14 days. "
            "Models future activity probability — low-probability users are the at-risk cohort. "
            "Good for retention campaigns."
        ),
        default_horizon_days=14,
        output_property_prefix="predicted_p_active_next",
        requires_user_event=False,
        requires_activity_resolution=True,
        training_population_spec={"kind": "performed_event_within_days", "days": 60},
        inference_population_spec={"kind": "performed_event_within_days", "days": 60},
        notes=(
            "Predicts activity probability. Users with a low score (e.g. p < 0.2) are at risk. "
            "Create the 'At risk of inactivity' cohort using a low threshold on the prediction score, "
            "not by modeling the absence of an event directly."
        ),
    ),
    "return_after_first_use": AutoresearchTemplate(
        key="return_after_first_use",
        display_name="Likely to return after first use",
        description=(
            "Predict which new users will have a second active session within 7 days. "
            "Works without a custom signup event — uses first-seen date. Good for onboarding."
        ),
        default_horizon_days=7,
        output_property_prefix="predicted_p_return_after_signup",
        requires_user_event=False,
        requires_activity_resolution=True,
        training_population_spec={"kind": "person_first_seen_within_days", "days": 14},
        inference_population_spec={"kind": "person_first_seen_within_days", "days": 14},
        notes=(
            "Population is users first seen in the last 14 days. "
            "Target event (second-session activity) is resolved from your event schema."
        ),
    ),
    "feature_adoption": AutoresearchTemplate(
        key="feature_adoption",
        display_name="Likely to adopt a feature",
        description=(
            "Predict which active users will use a selected feature for the first time within 14 days. "
            "Requires you to choose the feature's event or action."
        ),
        default_horizon_days=14,
        output_property_prefix="predicted_p_adopt",
        requires_user_event=True,
        requires_activity_resolution=False,
        training_population_spec={"kind": "active_not_performed_target", "active_within_days": 30},
        inference_population_spec={"kind": "active_not_performed_target", "active_within_days": 30},
        notes=(
            "Population automatically excludes users who have already performed the selected event/action — "
            "adoption mode predicts first-time use. Circular population is caught by validation."
        ),
    ),
    "repeat_key_behavior": AutoresearchTemplate(
        key="repeat_key_behavior",
        display_name="Likely to repeat a key behavior",
        description=(
            "Predict which users who have already done a key action will do it again within 7 days. "
            "Good for feature retention, power usage, and repeat purchases."
        ),
        default_horizon_days=7,
        output_property_prefix="predicted_p_repeat",
        requires_user_event=True,
        requires_activity_resolution=False,
        training_population_spec={"kind": "ever_performed_event"},
        inference_population_spec={"kind": "ever_performed_event"},
        notes=(
            "Population includes only users who have performed the selected event/action at least once. "
            "Continuation mode predicts repeat occurrence."
        ),
    ),
}


def resolve_activity_event(team: Team) -> tuple[str, list[str]]:
    """
    Discover the best activity event for universal activity templates.

    Queries the last 30 days of events, checks for preferred activity events
    ($pageview, $screen, $autocapture) in priority order, and falls back to the
    highest-volume non-noisy event if none of the preferred events exist.

    Returns (resolved_event, alternatives) where alternatives are other viable
    events the user can choose as an override.
    """
    try:
        query = HogQLQuery(
            query="""
                SELECT event, count() AS c
                FROM events
                WHERE timestamp >= now() - toIntervalDay(30)
                  AND timestamp < now()
                GROUP BY event
                ORDER BY c DESC
                LIMIT 100
            """,
        )
        tag_queries(product=Product.AUTORESEARCH, feature=Feature.QUERY)
        runner = HogQLQueryRunner(query=query, team=team)
        result = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)

        seen: dict[str, int] = {}
        if result.results:
            for row in result.results:
                event_name = str(row[0])
                count = int(row[1] or 0)
                if event_name not in _NOISY_EVENTS:
                    seen[event_name] = count

        for preferred in _PREFERRED_ACTIVITY_EVENTS:
            if preferred in seen:
                alts = [e for e in _PREFERRED_ACTIVITY_EVENTS if e in seen and e != preferred]
                for event, _ in sorted(seen.items(), key=lambda x: x[1], reverse=True):
                    if event not in alts and event != preferred and len(alts) < 4:
                        alts.append(event)
                return preferred, alts

        if seen:
            sorted_events = sorted(seen.items(), key=lambda x: x[1], reverse=True)
            resolved = sorted_events[0][0]
            return resolved, [e for e, _ in sorted_events[1:4]]

    except Exception:
        logger.exception("autoresearch_activity_resolver_error", team_id=team.pk)

    return "$pageview", []


@dataclass
class ResolvedTemplate:
    template_key: str
    display_name: str
    description: str
    target_event: str
    resolved_activity_event: Optional[str]
    activity_event_alternatives: list[str]
    horizon_days: int
    training_population: dict[str, Any]
    inference_population: dict[str, Any]
    output_person_property: str
    suggested_name: str
    notes: str


def resolve_template(
    team: Team,
    template_key: str,
    target_event_override: Optional[str] = None,
    horizon_days_override: Optional[int] = None,
) -> ResolvedTemplate:
    """
    Resolve a template key + optional overrides into a concrete pipeline config.

    Raises ValueError if template_key is unknown or a required override is missing.
    The returned ResolvedTemplate can be passed directly to pipeline creation.
    """
    template = TEMPLATES.get(template_key)
    if template is None:
        raise ValueError(f"Unknown template '{template_key}'. Available: {', '.join(TEMPLATES)}")

    if template.requires_user_event and not target_event_override:
        raise ValueError(
            f"Template '{template_key}' requires a target_event override. "
            "Provide the event or action name you want to predict."
        )

    resolved_activity: Optional[str] = None
    alternatives: list[str] = []

    if template.requires_activity_resolution:
        resolved_activity, alternatives = resolve_activity_event(team)
        target_event = target_event_override or resolved_activity
    else:
        target_event = target_event_override or ""

    horizon_days = horizon_days_override if horizon_days_override is not None else template.default_horizon_days

    # Append the horizon so two pipelines on the same target but different horizons write to
    # distinct person properties instead of clobbering one another. The horizon lives in the
    # suffix (not the prefix) so it tracks a horizon override rather than the template default.
    if template.requires_user_event and target_event:
        safe_name = target_event.lstrip("$").replace(" ", "_").lower()
        output_person_property = f"{template.output_property_prefix}_{safe_name}_{horizon_days}d"
    else:
        output_person_property = f"{template.output_property_prefix}_{horizon_days}d"

    training_population = _fill_population(template.training_population_spec, target_event)
    inference_population = _fill_population(template.inference_population_spec, target_event)

    if template.requires_user_event and target_event:
        safe_label = target_event.lstrip("$").replace("_", " ")
        suggested_name = f"{template.display_name}: {safe_label}"
    else:
        suggested_name = template.display_name

    return ResolvedTemplate(
        template_key=template_key,
        display_name=template.display_name,
        description=template.description,
        target_event=target_event,
        resolved_activity_event=resolved_activity,
        activity_event_alternatives=alternatives,
        horizon_days=horizon_days,
        training_population=training_population,
        inference_population=inference_population,
        output_person_property=output_person_property,
        suggested_name=suggested_name,
        notes=template.notes,
    )


def _fill_population(spec: dict[str, Any], target_event: str) -> dict[str, Any]:
    """Substitute the resolved target_event into a population spec."""
    result = dict(spec)
    kind = result.get("kind", "")
    if kind in ("active_not_performed_target", "ever_performed_event") and target_event:
        result["event"] = target_event
    return result
