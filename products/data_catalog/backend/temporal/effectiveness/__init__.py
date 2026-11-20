from typing import TYPE_CHECKING

from .activities import list_effectiveness_teams, measure_effectiveness
from .workflows import DataCatalogEffectivenessWorkflow

if TYPE_CHECKING:
    from posthog.temporal.common.registration import ActivityDefinition

WORKFLOWS = [DataCatalogEffectivenessWorkflow]
ACTIVITIES: list[ActivityDefinition] = [list_effectiveness_teams, measure_effectiveness]
