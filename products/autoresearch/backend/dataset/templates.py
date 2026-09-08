"""
Built-in autoresearch prediction templates.

Each template resolves to the same pipeline config shape as a custom pipeline,
so validation and creation work identically whether the user started from a template
or built a fully custom definition.

Population specs use a semantic format compiled to HogQL by
labeling._build_population_kind_conditions. Supported kinds:
  performed_event_within_days   users who did `event` (any event when omitted) in
                                the last `days` days
  person_first_seen_within_days users whose first-seen date is within `days` days
  active_not_performed_target   active users (any event in `active_within_days`) who
                                have NOT performed the pipeline's target
  ever_performed_event          users who have performed `event` at least once
  ever_performed_target         users who have performed the pipeline's target at least once

"Ever" and "has not performed" are bounded to the pipeline's training lookback
window. The target-relative kinds compile against the pipeline's target
predicate, so an action target matches by its matcher rather than its name.
Every kind is evaluated per user at T0 during training and as of the cutoff at
inference — see the compiler's docstring for the semantics.

Templates take an event name as their target. An action target is set through the
pipeline's `target_definition` at creation, outside template resolution.
"""

from __future__ import annotations

import re
import hashlib
from typing import Any, Optional

from posthog.schema import HogQLQuery

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.models.team.team import Team
from posthog.models.user import User

from products.autoresearch.backend.dataset.labeling import _identified_users_and_clause
from products.autoresearch.backend.query import run_hogql_rows

# Checked in this order when resolving an activity event for universal templates
_PREFERRED_ACTIVITY_EVENTS = ["$pageview", "$screen", "$autocapture"]
_MAX_ACTIVITY_ALTERNATIVES = 4

# The resolver hands its result to pipeline creation, so it must fit the pipeline's columns:
# `AutoresearchPipeline.target_event`, `.name` and `.output_person_property` are all 255 wide.
_PIPELINE_FIELD_MAX_LENGTH = 255

_UNSAFE_PROPERTY_CHARS = re.compile(r"[^a-z0-9._-]+")


@frozen
class AutoresearchTemplate:
    key: str
    display_name: str
    description_template: str
    default_horizon_days: int
    output_property_prefix: str
    requires_user_event: bool  # user must supply target_event override
    requires_activity_resolution: bool  # target_event resolved from schema
    training_population_spec: dict[str, Any]
    inference_population_spec: dict[str, Any]
    notes: str = ""

    @property
    def description(self) -> str:
        return self.describe(self.default_horizon_days)

    def describe(self, horizon_days: int) -> str:
        return self.description_template.format(horizon_days=horizon_days)


TEMPLATES: dict[str, AutoresearchTemplate] = {
    "likely_active_soon": AutoresearchTemplate(
        key="likely_active_soon",
        display_name="Likely active soon",
        description_template=(
            "Predict which active users will be active again in the next {horizon_days} days. "
            "Works for any product that sends pageview or screen events."
        ),
        default_horizon_days=7,
        output_property_prefix="predicted_p_active_soon",
        requires_user_event=False,
        requires_activity_resolution=True,
        training_population_spec={"kind": "performed_event_within_days", "days": 30},
        inference_population_spec={"kind": "performed_event_within_days", "days": 30},
        notes=(
            "The activity event is resolved from your event schema, preferring $pageview, then $screen, "
            "then $autocapture, then the custom event with the most identified users. You can override it."
        ),
    ),
    "at_risk_of_inactivity": AutoresearchTemplate(
        key="at_risk_of_inactivity",
        display_name="At risk of inactivity",
        description_template=(
            "Find users who are unlikely to be active in the next {horizon_days} days. "
            "The model predicts the probability of activity, so users with a low score are the at-risk group."
        ),
        default_horizon_days=14,
        output_property_prefix="predicted_p_active_next",
        requires_user_event=False,
        requires_activity_resolution=True,
        training_population_spec={"kind": "performed_event_within_days", "days": 60},
        inference_population_spec={"kind": "performed_event_within_days", "days": 60},
        notes=(
            "The score is the probability of activity. Build the at-risk cohort with a low threshold "
            "on the score, for example below 0.2, instead of modeling the absence of an event."
        ),
    ),
    "return_after_first_use": AutoresearchTemplate(
        key="return_after_first_use",
        display_name="Likely to return after first use",
        description_template=(
            "Predict which new users will be active again within {horizon_days} days. "
            "Uses the person's first-seen date, so it does not need a signup event."
        ),
        default_horizon_days=7,
        output_property_prefix="predicted_p_return_after_signup",
        requires_user_event=False,
        requires_activity_resolution=True,
        training_population_spec={"kind": "person_first_seen_within_days", "days": 14},
        inference_population_spec={"kind": "person_first_seen_within_days", "days": 14},
        notes=(
            "The population is users first seen in the last 14 days. The activity event is resolved "
            "from your event schema. Any activity after the sampled anchor point counts, including "
            "activity later in the same first session."
        ),
    ),
    "feature_adoption": AutoresearchTemplate(
        key="feature_adoption",
        display_name="Likely to adopt a feature",
        description_template=(
            "Predict which active users will use a selected feature for the first time within {horizon_days} days. "
            "Choose the feature's event."
        ),
        default_horizon_days=14,
        output_property_prefix="predicted_p_adopt",
        requires_user_event=True,
        requires_activity_resolution=False,
        training_population_spec={"kind": "active_not_performed_target", "active_within_days": 30},
        inference_population_spec={"kind": "active_not_performed_target", "active_within_days": 30},
        notes=(
            "The population is users active in the last 30 days who have not performed the selected event "
            "within the training lookback window. Use before that window does not exclude a user."
        ),
    ),
    "repeat_key_behavior": AutoresearchTemplate(
        key="repeat_key_behavior",
        display_name="Likely to repeat a key behavior",
        description_template=(
            "Predict which users who have already done a key action will do it again within {horizon_days} days. "
            "Useful for feature retention, power usage, and repeat purchases."
        ),
        default_horizon_days=7,
        output_property_prefix="predicted_p_repeat",
        requires_user_event=True,
        requires_activity_resolution=False,
        training_population_spec={"kind": "ever_performed_target"},
        inference_population_spec={"kind": "ever_performed_target"},
        notes=(
            "The population is users who performed the selected event at least once within the training "
            "lookback window."
        ),
    ),
}


def _is_activity_candidate(event: str) -> bool:
    # PostHog's own events carry a `$` prefix. Outside the preferred activity events they are
    # SDK bookkeeping ($identify, $feature_flag_called, $groupidentify, ...), not user behavior.
    if event in _PREFERRED_ACTIVITY_EVENTS:
        return True
    return not event.startswith("$") and len(event) <= _PIPELINE_FIELD_MAX_LENGTH


def resolve_activity_event(team: Team, user: Optional[User] = None) -> tuple[Optional[str], list[str]]:
    """
    Discover the best activity event for universal activity templates.

    Ranks the last 30 days of events by identified persons, checks for preferred
    activity events ($pageview, $screen, $autocapture) in priority order, and falls
    back to the custom event with the widest identified-person coverage.

    Returns (resolved_event, alternatives) where alternatives are other viable
    events the user can choose as an override. `resolved_event` is None when the
    team has no candidate. `user` is the person HogQL applies access control for;
    see `query.run_hogql`.
    """
    # Training and scoring only ever see identified users, so rank candidates on that
    # same population: anonymous-only traffic must not choose the activity event.
    identified_clause = _identified_users_and_clause()
    preferred_literal = ", ".join(f"'{event}'" for event in _PREFERRED_ACTIVITY_EVENTS)
    # Preferred events sort first so the row limit cannot drop them on teams with many event names.
    query = HogQLQuery(
        query=f"""
            SELECT event, uniq(person_id) AS c
            FROM events
            WHERE timestamp >= now() - toIntervalDay(30)
              AND timestamp < now(){identified_clause}
              AND (event IN ({preferred_literal}) OR event NOT LIKE '$%')
            GROUP BY event
            ORDER BY event IN ({preferred_literal}) DESC, c DESC, event
            LIMIT 100
        """,
    )
    tag_queries(product=Product.AUTORESEARCH, feature=Feature.QUERY)
    rows = run_hogql_rows(team=team, query=query, user=user)

    seen: dict[str, int] = {}
    for row in rows or []:
        event_name = str(row[0])
        if _is_activity_candidate(event_name):
            seen[event_name] = int(row[1] or 0)
    ranked = [event for event, _ in sorted(seen.items(), key=lambda item: (-item[1], item[0]))]

    resolved = next((preferred for preferred in _PREFERRED_ACTIVITY_EVENTS if preferred in seen), None)
    if resolved is None:
        if not ranked:
            return None, []
        resolved = ranked[0]

    alternatives = [event for event in _PREFERRED_ACTIVITY_EVENTS if event in seen and event != resolved]
    for event in ranked:
        if len(alternatives) >= _MAX_ACTIVITY_ALTERNATIVES:
            break
        if event != resolved and event not in alternatives:
            alternatives.append(event)
    return resolved, alternatives


@frozen
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


def _target_digest(target_event: str) -> str:
    # Upper case on purpose: a normalized name is all lower case, so a name that carries a
    # digest can never equal an event name that needed no normalization.
    return hashlib.sha256(target_event.encode()).hexdigest()[:6].upper()


def _safe_target_name(target_event: str) -> str:
    raw = target_event.lstrip("$")
    safe = _UNSAFE_PROPERTY_CHARS.sub("_", raw.lower()).strip("_") or "target"
    if safe == raw:
        return safe
    # Normalization is lossy ("Checkout Started" and "checkout_started" collapse to one name),
    # so a stable digest of the original keeps two such targets on separate person properties.
    return f"{safe}_{_target_digest(target_event)}"


def _output_person_property(prefix: str, target_event: str, horizon_days: int) -> str:
    # The target and the horizon are both part of the name: two pipelines that share one
    # but not the other must not $set the same person property and clobber each other's scores.
    suffix = f"_{horizon_days}d"
    name = f"{prefix}_{_safe_target_name(target_event)}"
    room = _PIPELINE_FIELD_MAX_LENGTH - len(suffix)
    if len(name) > room:
        digest = _target_digest(target_event)
        name = f"{name[: room - len(digest) - 1].rstrip('_')}_{digest}"
    return f"{name}{suffix}"


def resolve_template(
    team: Team,
    template_key: str,
    target_event_override: Optional[str] = None,
    horizon_days_override: Optional[int] = None,
    user: Optional[User] = None,
) -> ResolvedTemplate:
    """
    Resolve a template key + optional overrides into a concrete pipeline config.

    Raises ValueError if template_key is unknown, a required override is missing, the
    horizon is not positive, or no activity event can be resolved for the team.
    The returned ResolvedTemplate can be passed directly to pipeline creation.
    """
    template = TEMPLATES.get(template_key)
    if template is None:
        raise ValueError(f"Unknown template '{template_key}'. Available: {', '.join(TEMPLATES)}")

    if template.requires_user_event and not target_event_override:
        raise ValueError(
            f"Template '{template_key}' requires a target_event override. Provide the event name you want to predict."
        )

    if horizon_days_override is not None and horizon_days_override < 1:
        raise ValueError("horizon_days must be at least 1.")

    if target_event_override and len(target_event_override) > _PIPELINE_FIELD_MAX_LENGTH:
        raise ValueError(f"target_event must be at most {_PIPELINE_FIELD_MAX_LENGTH} characters.")

    resolved_activity: Optional[str] = None
    alternatives: list[str] = []

    if template.requires_activity_resolution:
        resolved_activity, alternatives = resolve_activity_event(team, user=user)
        target_event = target_event_override or resolved_activity or ""
        if not target_event:
            raise ValueError(
                f"Template '{template_key}' could not resolve an activity event: no identified users "
                "sent a usable event in the last 30 days. Provide target_event to choose one."
            )
    else:
        target_event = target_event_override or ""

    horizon_days = horizon_days_override if horizon_days_override is not None else template.default_horizon_days

    training_population = dict(template.training_population_spec)
    inference_population = dict(template.inference_population_spec)
    if template.requires_activity_resolution:
        # "Active" means the resolved activity event, for the population as much as for the label.
        # Without the event key the kind admits anyone who sent any event, bookkeeping included.
        for population in (training_population, inference_population):
            if population["kind"] == "performed_event_within_days":
                population["event"] = target_event

    if template.requires_user_event:
        safe_label = target_event.lstrip("$").replace("_", " ")
        suggested_name = f"{template.display_name}: {safe_label}"[:_PIPELINE_FIELD_MAX_LENGTH]
    else:
        suggested_name = template.display_name

    return ResolvedTemplate(
        template_key=template_key,
        display_name=template.display_name,
        description=template.describe(horizon_days),
        target_event=target_event,
        resolved_activity_event=resolved_activity,
        activity_event_alternatives=alternatives,
        horizon_days=horizon_days,
        training_population=training_population,
        inference_population=inference_population,
        output_person_property=_output_person_property(template.output_property_prefix, target_event, horizon_days),
        suggested_name=suggested_name,
        notes=template.notes,
    )
