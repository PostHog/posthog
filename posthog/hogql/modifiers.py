from typing import TYPE_CHECKING, Optional


from posthog.schema import (
    HogQLQueryModifiers,
    InCohortVia,
    MaterializationMode,
    PersonsArgMaxVersion,
    PersonsOnEventsMode,
    BounceRatePageViewMode,
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
    if modifiers.persons_on_events_mode is None:
        modifiers.persons_on_events_mode = team.person_on_events_mode or PersonsOnEventsMode.DISABLED

    if modifiers.persons_arg_max_version is None:
        modifiers.persons_arg_max_version = PersonsArgMaxVersion.AUTO

    if modifiers.in_cohort_via is None:
        modifiers.in_cohort_via = InCohortVia.AUTO

    if modifiers.materialization_mode is None or modifiers.materialization_mode == MaterializationMode.AUTO:
        modifiers.materialization_mode = MaterializationMode.LEGACY_NULL_AS_NULL

    if modifiers.optimize_joined_filters is None:
        modifiers.optimize_joined_filters = False

    if modifiers.bounce_rate_page_view_mode is None:
        modifiers.bounce_rate_page_view_mode = BounceRatePageViewMode.COUNT_PAGEVIEWS


def set_default_in_cohort_via(modifiers: HogQLQueryModifiers) -> HogQLQueryModifiers:
    if modifiers.in_cohort_via is None or modifiers.in_cohort_via == InCohortVia.AUTO:
        modifiers.in_cohort_via = InCohortVia.SUBQUERY

    return modifiers
