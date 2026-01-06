import hashlib
from abc import ABC, abstractmethod

from django.db.models import Q, QuerySet

import orjson

from posthog.event_usage import report_user_action
from posthog.models import EventDefinition, EventSchema, SchemaPropertyGroupProperty


class EventDefinitionGenerator(ABC):
    """
    Abstract base class for all event definition code generators.
    """

    @abstractmethod
    def generator_version(self) -> str:
        """
        Version of the generator - increment when changing output structure
        This ensures clients know to regenerate even when schemas don't change
        """
        pass

    @abstractmethod
    def language_name(self) -> str:
        """
        Return the human-readable language name (e.g., 'Go', 'TypeScript')
        """
        pass

    @abstractmethod
    def generate(
        self, event_definitions: QuerySet[EventDefinition], schema_map: dict[str, list[SchemaPropertyGroupProperty]]
    ) -> str:
        """
        Generate (multiline) code for the given event definitions and their schemas.
        """
        pass

    def calculate_schema_hash(
        self,
        event_definitions: QuerySet[EventDefinition],
        schema_map: dict[str, list[SchemaPropertyGroupProperty]],
    ) -> str:
        """
        Calculate a deterministic hash of the event schemas and generator version.
        The hash is used by clients to know when to regenerate their code.
        """
        schema_data = []
        for event_def in event_definitions:
            properties = schema_map.get(str(event_def.id), [])
            prop_data = [(p.name, p.property_type, p.is_required) for p in properties]
            # Sort properties by name for deterministic ordering
            schema_data.append((event_def.name, sorted(prop_data)))

        # Sort events by name for deterministic ordering
        schema_data.sort(key=lambda x: x[0])

        # Include generator version to force regeneration on structural changes
        hash_input = {
            "version": self.generator_version(),
            "schemas": schema_data,
        }

        return hashlib.sha256(orjson.dumps(hash_input, option=orjson.OPT_SORT_KEYS)).hexdigest()[:32]

    def record_report_generation(self, user, team_id: int, project_id: int) -> None:
        """
        A convenience method to structurally report telemetry for code generation.
        """
        report_user_action(
            user,
            "event definitions generated",
            {
                "language": self.language_name(),
                "generator_version": self.generator_version(),
                "team_id": team_id,
                "project_id": project_id,
            },
        )

    def fetch_event_definitions_and_schemas(
        self,
        project_id: int,
    ) -> tuple[QuerySet[EventDefinition], dict[str, list[SchemaPropertyGroupProperty]]]:
        """
        Fetch event definitions and build schema map. The key of `schema_map` references a EventDefinition.ID
        from the returned event_definitions set.
        """
        # System events that users should be able to manually capture
        # These are commonly used in user code and should be typed
        included_system_events = [
            "$pageview",  # Manually captured in SPAs (React Router, Vue Router, etc.)
            "$pageleave",  # Sometimes manually captured alongside $pageview
            "$screen",  # Manually captured in mobile apps (iOS, Android, React Native, Flutter)
        ]

        # Fetch event definitions: either non-system events or explicitly included system events
        event_definitions = (
            EventDefinition.objects.filter(team__project_id=project_id)
            .filter(
                Q(name__in=included_system_events)  # Include whitelisted system events
                | ~Q(name__startswith="$")  # Include all non-system events
            )
            .order_by("name")
        )

        # Fetch all event schemas with their property groups
        event_schemas = (
            EventSchema.objects.filter(event_definition__team__project_id=project_id)
            .select_related("property_group")
            .prefetch_related("property_group__properties")
        )

        # Build a mapping of event_definition_id -> property group properties
        schema_map: dict[str, list[SchemaPropertyGroupProperty]] = {}
        for event_schema in event_schemas:
            event_id = str(event_schema.event_definition_id)
            if event_id not in schema_map:
                schema_map[event_id] = []
            schema_map[event_id].extend(event_schema.property_group.properties.all())

        return event_definitions, schema_map
