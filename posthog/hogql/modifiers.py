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
    PersonsOnEventsMode,
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
    # Resolve the flag-based persons-on-events default here (the boundary, where the Team and
    # flags live) and inject it as plain data, so the pure builder never touches the Team. Only
    # evaluate the flag when the caller hasn't already set the mode.
    needs_persons_on_events = modifiers is None or modifiers.personsOnEventsMode is None
    return create_default_modifiers_for_team_context(
        HogQLTeamContext.from_team(team),
        modifiers,
        cloud=is_cloud(),
        persons_on_events=team.person_on_events_mode_flag_based_default if needs_persons_on_events else None,
    )


def set_default_modifier_values(modifiers: "HogQLQueryModifiers", team: "Team") -> None:
    """Fill modifier defaults in place from a Django ``Team``.

    Kept for existing callers, including ``Team.default_modifiers``. Resolves the flag-based
    ``personsOnEventsMode`` from the team at the boundary and injects it, then applies the
    team-independent defaults.
    """
    apply_modifier_defaults(
        modifiers,
        cloud=is_cloud(),
        persons_on_events=team.person_on_events_mode_flag_based_default
        if modifiers.personsOnEventsMode is None
        else None,
    )


# ---- Pure engine (no Team, no DB, no feature flags) ------------------------


def create_default_modifiers_for_team_context(
    team_context: HogQLTeamContext,
    modifiers: Optional["HogQLQueryModifiers"] = None,
    *,
    cloud: bool,
    persons_on_events: Optional[PersonsOnEventsMode] = None,
) -> "HogQLQueryModifiers":
    """Resolve default HogQL modifiers from plain team-context data.

    Pure: no Django model access, no database query, no flag or deploy-setting evaluation.
    ``cloud`` and ``persons_on_events`` arrive as already-resolved boundary values — the
    latter is the team's flag-based persons-on-events default, evaluated on the Django side
    and injected (``None`` to leave the mode unset, e.g. the standalone/test path).
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

    apply_modifier_defaults(modifiers, cloud=cloud, persons_on_events=persons_on_events)

    return modifiers


def apply_modifier_defaults(
    modifiers: "HogQLQueryModifiers", *, cloud: bool, persons_on_events: Optional[PersonsOnEventsMode] = None
) -> None:
    """Fill modifier defaults in place from already-resolved boundary values.

    ``cloud`` (``is_cloud()``) and ``persons_on_events`` (the team's flag-based persons-on-events
    default) are both resolved on the Django side and injected, so this stays free of flag,
    deploy-setting, and ``Team`` access. ``persons_on_events`` is applied only when the caller
    hasn't already set the mode; pass ``None`` to leave it unset (the standalone/test path).
    """
    if modifiers.personsOnEventsMode is None and persons_on_events is not None:
        modifiers.personsOnEventsMode = persons_on_events

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
