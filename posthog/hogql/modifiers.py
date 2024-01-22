from typing import Optional, TYPE_CHECKING

from posthog.schema import HogQLQueryModifiers, InCohortVia, MaterializationMode, PersonsArgMaxVersion
from posthog.utils import PersonOnEventsMode

if TYPE_CHECKING:
    from posthog.models import Team


def create_default_modifiers_for_team(
    team: "Team", modifiers: Optional[HogQLQueryModifiers] = None
) -> HogQLQueryModifiers:
    if modifiers is None:
        modifiers = HogQLQueryModifiers()
    else:
        modifiers = modifiers.model_copy()

    if modifiers.personsOnEventsMode is None:
        modifiers.personsOnEventsMode = team.person_on_events_mode or PersonOnEventsMode.DISABLED

    if modifiers.personsArgMaxVersion is None:
        modifiers.personsArgMaxVersion = PersonsArgMaxVersion.auto

    if modifiers.inCohortVia is None:
        modifiers.inCohortVia = InCohortVia.auto

    if modifiers.materializationMode is None or modifiers.materializationMode == MaterializationMode.auto:
        modifiers.materializationMode = MaterializationMode.legacy_null_as_null

    return modifiers


def set_default_in_cohort_via(modifiers: HogQLQueryModifiers) -> HogQLQueryModifiers:
    if modifiers.inCohortVia == InCohortVia.auto:
        modifiers.inCohortVia = InCohortVia.subquery

    return modifiers
