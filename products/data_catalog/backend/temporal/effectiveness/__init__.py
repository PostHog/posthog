from posthog.temporal.common.registration import ActivityDefinition

from .activities import list_effectiveness_teams, measure_effectiveness
from .workflows import DataCatalogEffectivenessWorkflow

WORKFLOWS = [DataCatalogEffectivenessWorkflow]
ACTIVITIES: list[ActivityDefinition] = [list_effectiveness_teams, measure_effectiveness]
