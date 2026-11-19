from collections.abc import Callable

from .activities import list_effectiveness_teams, measure_effectiveness
from .workflows import DataCatalogEffectivenessWorkflow

WORKFLOWS = [DataCatalogEffectivenessWorkflow]
ACTIVITIES: list[Callable[..., object]] = [list_effectiveness_teams, measure_effectiveness]
