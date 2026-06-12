from typing import TYPE_CHECKING, Optional

import posthoganalytics

from posthog.hogql.team_context import HogQLTeamContext

from posthog.cloud_utils import is_cloud
from posthog.schema_enums import (
    BounceRatePageViewMode,
    InCohortVia,
    InlineCohortCalculation,
    MaterializationMode,
    PersonsArgMaxVersion,
    PropertyGroupsMode,
    SessionsV2JoinMode,
    SessionTableVersion,
)

# This module loads at django.setup() via Team; posthog.schema (the pydantic models) is
# runtime-imported in the functions that build modifier objects to keep it off that path.
if TYPE_CHECKING:
    from posthog.schema import HogQLQueryModifiers

    from posthog.models import Team, User


# ---- Django boundary -------------------------------------------------------
# These keep their existing signatures (callers across the codebase and the Team
# model depend on them) and own the one default that needs the ORM: the flag-based
# personsOnEventsMode. Everything else is delegated to the pure functions below.


def create_default_modifiers_for_user(
    user: "User", team: "Team", modifiers: Optional["HogQLQueryModifiers"] = None
) -> "HogQLQueryModifiers":
    from posthog.schema import HogQLQueryModifiers  # noqa: PLC0415

    if modifiers is None:
        modifiers = HogQLQueryModifiers()
    else:
        modifiers = modifiers.model_copy()

    modifiers.useMaterializedViews = posthoganalytics.feature_enabled(
        "data-modeling",
        str(user.distinct_id),
        person_properties={
            "email": user.email,
        },
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )

    return create_default_modifiers_for_team(team, modifiers)


def create_default_modifiers_for_team(
    team: "Team", modifiers: Optional["HogQLQueryModifiers"] = None
) -> "HogQLQueryModifiers":
    modifiers = create_default_modifiers_for_team_context(HogQLTeamContext.from_team(team), modifiers, cloud=is_cloud())
    _resolve_persons_on_events_default(modifiers, team)
    return modifiers


def set_default_modifier_values(modifiers: "HogQLQueryModifiers", team: "Team") -> None:
    """Fill modifier defaults in place from a Django ``Team``.

    Kept for existing callers, including ``Team.default_modifiers``. Resolves the
    flag-based ``personsOnEventsMode`` from the team, then applies the
    team-independent defaults.
    """
    _resolve_persons_on_events_default(modifiers, team)
    apply_modifier_defaults(modifiers, cloud=is_cloud())


def _resolve_persons_on_events_default(modifiers: "HogQLQueryModifiers", team: "Team") -> None:
    # The persons-on-events default is a feature-flag / instance-setting evaluation
    # (see Team.person_on_events_mode_flag_based_default), so it stays at the Django
    # boundary and is resolved lazily — only when not already set. A later step will
    # turn it into an injected, already-resolved value.
    if modifiers.personsOnEventsMode is None:
        modifiers.personsOnEventsMode = team.person_on_events_mode_flag_based_default


# ---- Pure engine (no Team, no DB, no feature flags) ------------------------


def create_default_modifiers_for_team_context(
    team_context: HogQLTeamContext, modifiers: Optional["HogQLQueryModifiers"] = None, *, cloud: bool
) -> "HogQLQueryModifiers":
    """Resolve default HogQL modifiers from plain team-context data.

    Pure: no Django model access, no database query, no flag or deploy-setting
    evaluation — ``cloud`` arrives as an already-resolved boundary value.
    ``personsOnEventsMode`` is intentionally left untouched when not already set — its
    flag-based default is a boundary concern (see ``create_default_modifiers_for_team``).
    """
    from pydantic import ValidationError  # noqa: PLC0415

    from posthog.schema import CustomChannelRule, HogQLQueryModifiers  # noqa: PLC0415

    if modifiers is None:
        modifiers = HogQLQueryModifiers()
    else:
        modifiers = modifiers.model_copy()

    if modifiers.useMaterializedViews is None:
        modifiers.useMaterializedViews = True

    if isinstance(team_context.modifiers, dict):
        for key, value in team_context.modifiers.items():
            if getattr(modifiers, key, None) is None:
                if key == "customChannelTypeRules":
                    # don't break all queries if customChannelTypeRules are invalid
                    try:
                        if isinstance(value, list):
                            value = [CustomChannelRule(**rule) if isinstance(rule, dict) else rule for rule in value]
                            setattr(modifiers, key, value)
                    except ValidationError:
                        pass
                else:
                    setattr(modifiers, key, value)

    if modifiers.optimizeProjections is None:
        modifiers.optimizeProjections = True

    apply_modifier_defaults(modifiers, cloud=cloud)

    return modifiers


def apply_modifier_defaults(modifiers: "HogQLQueryModifiers", *, cloud: bool) -> None:
    """Fill all team-independent modifier defaults in place.

    ``personsOnEventsMode`` is intentionally not set here — it needs the team's
    flag-based default, resolved at the boundary. ``cloud`` is the deployment bool,
    likewise resolved at the boundary (``is_cloud()`` on the Django side).
    """
    if modifiers.personsArgMaxVersion is None:
        modifiers.personsArgMaxVersion = PersonsArgMaxVersion.AUTO

    if modifiers.inCohortVia is None:
        modifiers.inCohortVia = InCohortVia.AUTO

    if modifiers.materializationMode is None or modifiers.materializationMode == MaterializationMode.AUTO:
        modifiers.materializationMode = MaterializationMode.LEGACY_NULL_AS_NULL

    if modifiers.optimizeJoinedFilters is None:
        modifiers.optimizeJoinedFilters = False

    if modifiers.bounceRatePageViewMode is None:
        modifiers.bounceRatePageViewMode = BounceRatePageViewMode.COUNT_PAGEVIEWS

    if modifiers.sessionTableVersion is None:
        modifiers.sessionTableVersion = SessionTableVersion.AUTO

    if modifiers.sessionsV2JoinMode is None:
        modifiers.sessionsV2JoinMode = SessionsV2JoinMode.UUID

    if modifiers.useMaterializedViews is None:
        modifiers.useMaterializedViews = True

    if modifiers.propertyGroupsMode is None and cloud:
        modifiers.propertyGroupsMode = PropertyGroupsMode.OPTIMIZED

    if modifiers.convertToProjectTimezone is None:
        modifiers.convertToProjectTimezone = True

    if modifiers.inlineCohortCalculation is None:
        modifiers.inlineCohortCalculation = InlineCohortCalculation.AUTO

    if modifiers.sessionIdPushdown is None:
        modifiers.sessionIdPushdown = False

    if modifiers.sessionPropertyPreAggregation is None:
        modifiers.sessionPropertyPreAggregation = False


def set_default_in_cohort_via(modifiers: "HogQLQueryModifiers") -> "HogQLQueryModifiers":
    if modifiers.inCohortVia is None or modifiers.inCohortVia == InCohortVia.AUTO:
        modifiers.inCohortVia = InCohortVia.SUBQUERY

    return modifiers
