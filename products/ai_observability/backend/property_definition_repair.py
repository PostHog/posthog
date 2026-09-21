from typing import TYPE_CHECKING

from posthog.schema import AIEventType

from posthog.hogql_queries.ai.utils import HEAVY_PROPERTY_NAMES

from products.event_definitions.backend.models.event_definition import EventDefinition
from products.event_definitions.backend.models.property_definition import PropertyDefinition, effective_project_id_expr

if TYPE_CHECKING:
    from posthog.models.team import Team


class AIPropertyDefinitionRepair:
    def __init__(self, team: "Team") -> None:
        self.team = team

    def repair(self, *, dry_run: bool) -> list[str]:
        project_id = self.team.project_id
        has_ai_events = (
            EventDefinition.objects.alias(effective_project_id=effective_project_id_expr())
            .filter(effective_project_id=project_id, name__in=[event.value for event in AIEventType])
            .exists()
        )
        if not has_ai_events:
            return []

        existing_names = set(
            PropertyDefinition.objects.alias(effective_project_id=effective_project_id_expr())
            .filter(
                effective_project_id=project_id,
                name__in=HEAVY_PROPERTY_NAMES,
                type=PropertyDefinition.Type.EVENT,
                group_type_index__isnull=True,
            )
            .values_list("name", flat=True)
        )
        missing_names = sorted(HEAVY_PROPERTY_NAMES - existing_names)
        if not dry_run:
            PropertyDefinition.objects.bulk_create(
                [
                    PropertyDefinition(
                        team_id=self.team.id,
                        project_id=project_id,
                        name=name,
                        type=PropertyDefinition.Type.EVENT,
                    )
                    for name in missing_names
                ],
                ignore_conflicts=True,
            )
        return missing_names
