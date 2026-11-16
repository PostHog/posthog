from .activities import list_effectiveness_teams, measure_effectiveness
from .workflows import DataCatalogEffectivenessWorkflow

WORKFLOWS = [DataCatalogEffectivenessWorkflow]
ACTIVITIES = [list_effectiveness_teams, measure_effectiveness]
