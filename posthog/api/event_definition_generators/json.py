from django.db.models import QuerySet

import orjson

from posthog.api.event_definition_generators.base import EventDefinitionGenerator
from posthog.models import EventDefinition, SchemaPropertyGroupProperty


class JsonGenerator(EventDefinitionGenerator):
    def generator_version(self) -> str:
        return "0.0.1"

    def language_name(self) -> str:
        return "JSON"

    def generate(
        self,
        event_definitions: QuerySet[EventDefinition],
        schema_map: dict[str, list[SchemaPropertyGroupProperty]],
    ) -> str:
        """
        Generate a JSON representation of the event definitions and their schemas.
        """
        output_data = []

        for event_def in event_definitions:
            event_data = {
                "name": event_def.name,
                "description": getattr(event_def, "description", None),
                "properties": [],
            }

            # Get properties for this event
            properties = schema_map.get(str(event_def.id), [])

            # Sort properties by name for deterministic output
            sorted_properties = sorted(properties, key=lambda p: p.name)

            for prop in sorted_properties:
                event_data["properties"].append(
                    {
                        "name": prop.name,
                        "type": prop.property_type,
                        "required": prop.is_required,
                    }
                )

            output_data.append(event_data)

        # Return pretty-printed JSON
        return orjson.dumps(output_data, option=orjson.OPT_INDENT_2).decode("utf-8")
