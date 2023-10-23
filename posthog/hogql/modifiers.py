from typing import Optional

from posthog.models import Team
from posthog.schema import HogQLQueryModifiers
from posthog.utils import PersonOnEventsMode


def create_default_modifiers_for_team(
    team: Team, modifiers: Optional[HogQLQueryModifiers] = None
) -> HogQLQueryModifiers:
    if modifiers is None:
        modifiers = HogQLQueryModifiers()
    else:
        modifiers = modifiers.model_copy()

    if modifiers.personsOnEventsMode is None:
        modifiers.personsOnEventsMode = team.person_on_events_mode or PersonOnEventsMode.DISABLED

    if modifiers.personsArgMaxVersion is None:
        modifiers.personsArgMaxVersion = "auto"

    if modifiers.inCohortVia is None:
        modifiers.inCohortVia = "subquery"

    return modifiers
