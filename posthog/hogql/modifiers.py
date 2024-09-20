from typing import TYPE_CHECKING, Optional


from posthog.schema import (
    HogQLQueryModifiers,
    InCohortVia,
    MaterializationMode,
    PersonsArgMaxVersion,
    BounceRatePageViewMode,
    SessionTableVersion,
)

if TYPE_CHECKING:
    from posthog.models import Team


def create_default_modifiers_for_team(
    team: "Team", modifiers: Optional[HogQLQueryModifiers] = None
) -> HogQLQueryModifiers:
    if modifiers is None:
        modifiers = HogQLQueryModifiers()
    else:
        modifiers = modifiers.model_copy()

    if isinstance(team.modifiers, dict):
        for key, value in team.modifiers.items():
            if getattr(modifiers, key) is None:
                setattr(modifiers, key, value)

    set_default_modifier_values(modifiers, team)

    return modifiers


def set_default_modifier_values(modifiers: HogQLQueryModifiers, team: "Team"):
    if modifiers.personsOnEventsMode is None:
        modifiers.personsOnEventsMode = team.person_on_events_mode_flag_based_default

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


def set_default_in_cohort_via(modifiers: HogQLQueryModifiers) -> HogQLQueryModifiers:
    if modifiers.inCohortVia is None or modifiers.inCohortVia == InCohortVia.AUTO:
        modifiers.inCohortVia = InCohortVia.SUBQUERY

    return modifiers
