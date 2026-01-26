from typing import Literal, Union

from pydantic import BaseModel, Field

from posthog.models import Team, User
from posthog.sync import database_sync_to_async

from ee.hogai.chat_agent.query_planner.toolkit import TaxonomyAgentToolkit
from ee.hogai.external_tool import ExternalTool, ExternalToolResult, register_external_tool
from ee.hogai.utils.helpers import format_events_yaml


class ReadEventsQuery(BaseModel):
    kind: Literal["events"] = "events"


class ReadEventPropertiesQuery(BaseModel):
    kind: Literal["event_properties"] = "event_properties"
    event_name: str = Field(description="The name of the event that you want to retrieve properties for.")


class ReadEntityPropertiesQuery(BaseModel):
    kind: Literal["entity_properties"] = "entity_properties"
    entity: str = Field(description="The type of the entity that you want to retrieve properties for.")


class ReadActionPropertiesQuery(BaseModel):
    kind: Literal["action_properties"] = "action_properties"
    action_id: int


class ReadEntitySamplePropertyValuesQuery(BaseModel):
    kind: Literal["entity_property_values"] = "entity_property_values"
    entity: str = Field(description="The type of the entity that you want to retrieve properties for.")
    property_name: str = Field(description="Verified property name of an entity.")


class ReadEventSamplePropertyValuesQuery(BaseModel):
    kind: Literal["event_property_values"] = "event_property_values"
    event_name: str = Field(description="Verified event name")
    property_name: str = Field(description="Verified property name of an event.")


class ReadActionSamplePropertyValuesQuery(BaseModel):
    kind: Literal["action_property_values"] = "action_property_values"
    action_id: int = Field(description="Verified action ID")
    property_name: str = Field(description="Verified property name of an action.")


ReadTaxonomyQueryType = Union[
    ReadEventsQuery,
    ReadEventPropertiesQuery,
    ReadEventSamplePropertyValuesQuery,
    ReadEntityPropertiesQuery,
    ReadEntitySamplePropertyValuesQuery,
    ReadActionPropertiesQuery,
    ReadActionSamplePropertyValuesQuery,
]


class ReadTaxonomyExternalToolArgs(BaseModel):
    query: ReadTaxonomyQueryType = Field(..., discriminator="kind")


@register_external_tool
class ReadTaxonomyExternalTool(ExternalTool):
    """
    External version of ReadTaxonomyTool for API/MCP callers.

    Explores the user's taxonomy (events, actions, properties, and property values).
    """

    name = "read_taxonomy"
    args_schema = ReadTaxonomyExternalToolArgs

    async def execute(self, team: Team, user: User, **args) -> ExternalToolResult:
        query_data = args.get("query", {})

        try:
            validated_args = ReadTaxonomyExternalToolArgs(query=query_data)
            query = validated_args.query
        except Exception as e:
            return ExternalToolResult(
                success=False,
                content=f"Invalid query: {e}",
                error="validation_error",
            )

        toolkit = TaxonomyAgentToolkit(team)

        try:

            @database_sync_to_async(thread_sensitive=False)
            def _execute_query():
                res = ""
                match query:
                    case ReadEventsQuery():
                        res = format_events_yaml([], team)
                    case ReadEventPropertiesQuery():
                        res = toolkit.retrieve_event_or_action_properties(query.event_name)
                    case ReadEventSamplePropertyValuesQuery():
                        res = toolkit.retrieve_event_or_action_property_values(query.event_name, query.property_name)
                    case ReadActionPropertiesQuery():
                        res = toolkit.retrieve_event_or_action_properties(query.action_id)
                    case ReadActionSamplePropertyValuesQuery():
                        res = toolkit.retrieve_event_or_action_property_values(query.action_id, query.property_name)
                    case ReadEntityPropertiesQuery():
                        res = toolkit.retrieve_entity_properties(query.entity)
                    case ReadEntitySamplePropertyValuesQuery():
                        res = toolkit.retrieve_entity_property_values(query.entity, query.property_name)
                    case _:
                        return ExternalToolResult(
                            success=False,
                            content=f"Invalid query type: The query structure '{type(query).__name__}' is not recognized.",
                            error="validation_error",
                        )

                return ExternalToolResult(
                    success=True,
                    content=res,
                    data={"query": query_data},
                )

            return await _execute_query()
        except Exception as e:
            return ExternalToolResult(
                success=False,
                content=f"Failed to read taxonomy: {e}",
                error="execution_error",
            )
