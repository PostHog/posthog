from typing import Any, Literal, Self, Union

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field, create_model

from posthog.models import Team, User

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.graph.query_planner.toolkit import TaxonomyAgentToolkit
from ee.hogai.tool import MaxTool
from ee.hogai.utils.helpers import format_events_yaml
from ee.hogai.utils.types.base import AssistantState

READ_TAXONOMY_TOOL_DESCRIPTION = """
Use this tool to explore the user's taxonomy (i.e. data schema).
The user implements PostHog SDKs to collect events, properties, and property values. They are used by users to create insights with visualizations, SQL queries, watch session recordings, filter data, target particular users or groups by traits or behavior, etc.
Each event, action, and entity has its own data schema. You must verify that specific combinations exist before using it anywhere else.
Events or properties starting from "$" are system properties automatically captured by SDKs.

# Examples of when to use the read_taxonomy tool

<example>
User: What event can I use to track revenue?
Assistant: I'm going to retrieve events and event properties to help you find the event you're looking for.
*Retrieves events*
Assistant: I've found a few matching events. I'm going to retrieve event properties to help you find the event you're looking for.
*Retrieves event properties for each event*
Assistant: I've found a few matching properties. I'm going to retrieve sample property values for each property to verify they can be used for revenue tracking.
*Retrieves sample property values for each event property*
Assistant: I've found matching combinations...

<reasoning>
The assistant used the read_taxonomy tool because:
1. The user is asking about **their custom data schema** in PostHog.
2. The assistant needs to find a specific combination of events, properties, and property values that can be used to track revenue.
</reasoning>
</example>

# Examples of when NOT to use the read_taxonomy tool

<example>
User: What system properties does PostHog capture?
Assistant: I'm going to search PostHog documentation to find the system properties that are automatically captured by SDKs.
*Begins searching PostHog documentation*

<reasoning>
The assistant did not use the read_taxonomy tool because it is an informational request. The user is simply asking for documentation search.
</reasoning>
</example>
""".strip()


class ReadEvents(BaseModel):
    """Returns the list of available events. Events are sorted by their popularity where the most popular events are at the top."""

    kind: Literal["events"] = "events"


class ReadEventProperties(BaseModel):
    """Returns the properties list for a provided event. Before calling this tool, ensure the event exists by reading events."""

    kind: Literal["event_properties"] = "event_properties"
    event_name: str = Field(description="The name of the event that you want to retrieve properties for.")


class ReadEntityProperties(BaseModel):
    """Returns the properties list for a provided entity."""

    kind: Literal["entity_properties"] = "entity_properties"
    entity: str = Field(description="The type of the entity that you want to retrieve properties for.")
    """Keep entity as string to allow for dynamic entity types."""


class ReadActionProperties(BaseModel):
    """Returns the properties list for a provided action. Before calling this tool, ensure the action exists by searching actions or if it was provided in the context."""

    kind: Literal["action_properties"] = "action_properties"
    action_id: int


class ReadEntitySamplePropertyValues(BaseModel):
    """For a provided entity and a property, returns a list of maximum 25 sample values that the combination has."""

    kind: Literal["entity_property_values"] = "entity_property_values"
    entity: str = Field(description="The type of the entity that you want to retrieve properties for.")
    """Keep entity as string to allow for dynamic entity types."""
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


class ReadTaxonomyToolArgs(BaseModel):
    query: ReadTaxonomyQuery = Field(..., discriminator="kind")


class ReadTaxonomyTool(MaxTool):
    name: Literal["read_taxonomy"] = "read_taxonomy"
    description: str = READ_TAXONOMY_TOOL_DESCRIPTION
    context_prompt_template: str = (
        "Explores the user's events, actions, properties, and property values (i.e. taxonomy)."
    )
    thinking_message: str = "Searching the taxonomy"
    show_tool_call_message: bool = False

    def _run_impl(self, query: dict[str, Any]) -> tuple[str, Any]:
        # Langchain can't parse a dynamically created Pydantic model, so we need to additionally validate the query here.
        validated_query = ReadTaxonomyToolArgs(query=query).query
        toolkit = TaxonomyAgentToolkit(self._team)
        res = ""
        match validated_query:
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
                raise ValueError(f"Invalid query: {query}")
        return res, None

    @classmethod
    async def create_tool_class(
        cls,
        *,
        team: Team,
        user: User,
        state: AssistantState | None = None,
        config: RunnableConfig | None = None,
    ) -> Self:
        context_manager = AssistantContextManager(team, user, config)
        group_names = await context_manager.get_group_names()

        # Create Literal type with actual entity names
        EntityKind = Literal["person", "session", *group_names]  # type: ignore

        ReadEntityPropertiesWithGroups = create_model(
            "ReadEntityProperties",
            __base__=ReadEntityProperties,
            entity=(
                EntityKind,
                Field(description=ReadEntityProperties.model_fields["entity"].description),
            ),
        )

        ReadEntitySamplePropertyValuesWithGroups = create_model(
            "ReadEntitySamplePropertyValues",
            __base__=ReadEntitySamplePropertyValues,
            entity=(
                EntityKind,
                Field(description=ReadEntitySamplePropertyValues.model_fields["entity"].description),
            ),
        )

        ReadTaxonomyQueryWithGroups = Union[
            ReadEvents,
            ReadEventProperties,
            ReadEventSamplePropertyValues,
            ReadEntityPropertiesWithGroups,  # type: ignore[valid-type]
            ReadEntitySamplePropertyValuesWithGroups,  # type: ignore[valid-type]
            ReadActionProperties,
            ReadActionSamplePropertyValues,
        ]

        class ReadTaxonomyToolArgsWithGroups(BaseModel):
            query: ReadTaxonomyQueryWithGroups = Field(..., discriminator="kind")

        return cls(team=team, user=user, state=state, config=config, args_schema=ReadTaxonomyToolArgsWithGroups)
