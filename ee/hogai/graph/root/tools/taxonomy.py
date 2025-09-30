from typing import Literal, Union

from pydantic import BaseModel, Field

from ee.hogai.graph.query_planner.toolkit import TaxonomyAgentToolkit
from ee.hogai.tool import MaxTool
from ee.hogai.utils.helpers import format_events_yaml


class ReadEvents(BaseModel):
    """Returns the list of available events."""

    kind: Literal["events"] = "events"


class ReadEventProperties(BaseModel):
    """Returns the properties list for a provided event. Before calling this tool, ensure the event exists by reading events."""

    kind: Literal["event_properties"] = "event_properties"
    event_name: str = Field(description="The name of the event that you want to retrieve properties for.")


class ReadEntityProperties(BaseModel):
    """Returns the properties list for a provided entity."""

    kind: Literal["entity_properties"] = "entity_properties"
    entity: Literal["person", "session", "organization", "instance", "project", "customer"] = Field(
        description="The type of the entity that you want to retrieve properties for."
    )


class ReadActionProperties(BaseModel):
    """Returns the properties list for a provided event. Before calling this tool, ensure the action exists by searching actions or if it was provided in the context."""

    kind: Literal["action_properties"] = "action_properties"
    action_id: int


class ReadEntitySamplePropertyValues(BaseModel):
    """For a provided entity and a property, returns a list of maximum 25 sample values that the combination has."""

    kind: Literal["entity_property_values"] = "entity_property_values"
    entity: Literal["person", "session", "organization", "instance", "project", "customer"] = Field(
        description="The type of the entity that you want to retrieve properties for."
    )
    property_name: str = Field(description="Verified property name of an entity.")


class ReadEventSamplePropertyValues(BaseModel):
    """For a provided event and a property, returns a list of maximum 25 sample values that the combination has."""

    kind: Literal["event_property_values"] = "event_property_values"
    event_name: str = Field(description="Verified event name")
    property_name: str = Field(description="Verified property name of an event.")


class ReadActionSamplePropertyValues(BaseModel):
    """For a provided event and a property, returns a list of maximum 25 sample values that the combination has."""

    kind: Literal["action_property_values"] = "action_property_values"
    action_id: int = Field(description="Verified action ID")
    property_name: str = Field(description="Verified property name of an action.")


ReadTaxonomyQuery = Union[
    ReadEvents,
    ReadEventProperties,
    ReadEventSamplePropertyValues,
    ReadEntityProperties,
    ReadEntitySamplePropertyValues,
    ReadActionProperties,
    ReadActionSamplePropertyValues,
]


class ReadTaxonomy(BaseModel):
    query: ReadTaxonomyQuery = Field(..., discriminator="kind")


READ_TAXONOMY_TOOL_DESCRIPTION = """
Use this tool to explore the user's data schema (i.e. taxonomy).
The user implements PostHog SDKs to collect events, properties, and property values. They are used by users to create insights with visualizations, SQL queries, watch session recordings, filter data, target particular users or groups by traits or behavior, etc.
Each event, action, and entity has its own data schema. You must verify that specific combinations exist before using it anywhere else.
""".strip()


class ReadTaxonomyTool(MaxTool):
    name: Literal["ReadTaxonomy"] = "ReadTaxonomy"
    description: str = READ_TAXONOMY_TOOL_DESCRIPTION
    root_system_prompt_template: str = (
        "Explores the user's events, actions, properties, and property values (i.e. taxonomy)."
    )
    thinking_message: str = "Searching the taxonomy"
    args_schema: type[BaseModel] = ReadTaxonomy

    def _run_impl(self, query: ReadTaxonomyQuery) -> tuple[str, str]:
        toolkit = TaxonomyAgentToolkit(self._team)
        match query:
            case ReadEvents():
                res = format_events_yaml([], self._team)
            case ReadEventProperties() as schema:
                res = toolkit.retrieve_event_or_action_properties(schema.event_name)
            case ReadEventSamplePropertyValues() as schema:
                res = toolkit.retrieve_event_or_action_property_values(schema.event_name, schema.property_name)
            case ReadActionProperties() as schema:
                res = toolkit.retrieve_event_or_action_properties(schema.action_id)
            case ReadActionSamplePropertyValues() as schema:
                res = toolkit.retrieve_event_or_action_property_values(schema.action_id, schema.property_name)
            case ReadEntityProperties() as schema:
                res = toolkit.retrieve_entity_properties(schema.entity)
            case ReadEntitySamplePropertyValues() as schema:
                res = toolkit.retrieve_entity_property_values(schema.entity, schema.property_name)
            case _:
                raise ValueError(f"Invalid query: {query.query}")
        return res, res
