from posthog.hogql.database.schema.channel_type import DEFAULT_CHANNEL_TYPES
from posthog.hogql_queries.ai.actors_property_taxonomy_query_runner import ActorsPropertyTaxonomyQueryRunner
from posthog.hogql_queries.ai.event_taxonomy_query_runner import EventTaxonomyQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Action, Team
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.property_definition import PropertyDefinition, PropertyType
from posthog.schema import (
    ActorsPropertyTaxonomyQuery,
    CachedActorsPropertyTaxonomyQueryResponse,
    CachedEventTaxonomyQueryResponse,
    EventTaxonomyQuery,
)
from langgraph.graph.state import StateGraph


from functools import cached_property
from typing import Generic, TypeVar, Optional, cast, Literal, get_args, get_origin
from collections.abc import Iterable
from pydantic import BaseModel, Field
from posthog.models.user import User
from ..utils.types import (
    AssistantNodeName,
)
from .taxonomy_toolkit_types import TaxonomyNodeName
from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP
from .base import TaxonomyNode
from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer


class retrieve_event_properties(BaseModel):
    """
    Use this tool to retrieve the property names of an event. You will receive a list of properties containing their name, value type, and description, or a message that properties have not been found.

    - **Try other events** if the tool doesn't return any properties.
    - **Prioritize properties that are directly related to the context or objective of the user's query.**
    - **Avoid using ambiguous properties** unless their relevance is explicitly confirmed.
    """

    event_name: str = Field(..., description="The name of the event that you want to retrieve properties for.")


class retrieve_action_properties(BaseModel):
    """
    Use this tool to retrieve the property names of an action. You will receive a list of properties containing their name, value type, and description, or a message that properties have not been found.

    - **Try other actions or events** if the tool doesn't return any properties.
    - **Prioritize properties that are directly related to the context or objective of the user's query.**
    - **Avoid using ambiguous properties** unless their relevance is explicitly confirmed.
    """

    action_id: int = Field(..., description="The ID of the action that you want to retrieve properties for.")


class retrieve_entity_properties(BaseModel):
    """
    Use this tool to retrieve property names for a property group (entity). You will receive a list of properties containing their name, value type, and description, or a message that properties have not been found.

    - **Infer the property groups from the user's request.**
    - **Try other entities** if the tool doesn't return any properties.
    - **Prioritize properties that are directly related to the context or objective of the user's query.**
    - **Avoid using ambiguous properties** unless their relevance is explicitly confirmed.
    """

    entity: Literal["person", "session"] = Field(
        ..., description="The type of the entity that you want to retrieve properties for."
    )


class retrieve_event_property_values(BaseModel):
    """
    Use this tool to retrieve the property values for an event. Adjust filters to these values. You will receive a list of property values or a message that property values have not been found. Some properties can have many values, so the output will be truncated. Use your judgment to find a proper value.
    """

    event_name: str = Field(..., description="The name of the event that you want to retrieve values for.")
    property_name: str = Field(..., description="The name of the property that you want to retrieve values for.")


class retrieve_action_property_values(BaseModel):
    """
    Use this tool to retrieve the property values for an action. Adjust filters to these values. You will receive a list of property values or a message that property values have not been found. Some properties can have many values, so the output will be truncated. Use your judgment to find a proper value.
    """

    action_id: int = Field(..., description="The ID of the action that you want to retrieve values for.")
    property_name: str = Field(..., description="The name of the property that you want to retrieve values for.")


class retrieve_entity_property_values(BaseModel):
    """
    Use this tool to retrieve property values for a property name. Adjust filters to these values. You will receive a list of property values or a message that property values have not been found. Some properties can have many values, so the output will be truncated. Use your judgment to find a proper value.
    """

    entity: Literal["person", "session"] = Field(
        ..., description="The type of the entity that you want to retrieve properties for."
    )
    property_name: str = Field(..., description="The name of the property that you want to retrieve values for.")


class ask_user_for_help(BaseModel):
    """
    Use this tool to ask a question to the user. Your question must be concise and clear.
    """

    request: str = Field(..., description="The question you want to ask the user.")


# Type variables for the new generic classes
Output = TypeVar("Output", bound=BaseModel)
State = TypeVar("State", bound=BaseModel)
ToolInput = TypeVar("ToolInput", bound=BaseModel)


class TaxonomyAgentToolkit(Generic[Output, ToolInput]):
    """Base toolkit for taxonomy agents that handle tool execution."""

    def __init__(self, team: Team):
        self._team = team

    @property
    def _groups(self):
        return GroupTypeMapping.objects.filter(project_id=self._team.project_id).order_by("group_type_index")

    @cached_property
    def _entity_names(self) -> list[str]:
        """
        The schemas use `group_type_index` for groups complicating things for the agent. Instead, we use groups' names,
        so the generation step will handle their indexes. Tools would need to support multiple arguments, or we would need
        to create various tools for different group types. Since we don't use function calling here, we want to limit the
        number of tools because non-function calling models can't handle many tools.
        """
        entities = [
            "person",
            "session",
            *[group.group_type for group in self._groups],
        ]
        return entities

    def _enrich_props_with_descriptions(self, entity: str, props: Iterable[tuple[str, str | None]]):
        enriched_props = []
        mapping = {
            "session": CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"],
            "person": CORE_FILTER_DEFINITIONS_BY_GROUP["person_properties"],
            "event": CORE_FILTER_DEFINITIONS_BY_GROUP["event_properties"],
        }
        for prop_name, prop_type in props:
            description = None
            if entity_definition := mapping.get(entity, {}).get(prop_name):
                if entity_definition.get("system") or entity_definition.get("ignored_in_assistant"):
                    continue
                description = entity_definition.get("description_llm") or entity_definition.get("description")
            enriched_props.append((prop_name, prop_type, description))
        return enriched_props

    def _format_property_values(
        self, sample_values: list, sample_count: Optional[int] = 0, format_as_string: bool = False
    ) -> str:
        if len(sample_values) == 0 or sample_count == 0:
            return f"The property does not have any values in the taxonomy."

        # Add quotes to the String type, so the LLM can easily infer a type.
        # Strings like "true" or "10" are interpreted as booleans or numbers without quotes, so the schema generation fails.
        # Remove the floating point the value is an integer.
        formatted_sample_values: list[str] = []
        for value in sample_values:
            if format_as_string:
                formatted_sample_values.append(f'"{value}"')
            elif isinstance(value, float) and value.is_integer():
                formatted_sample_values.append(str(int(value)))
            else:
                formatted_sample_values.append(str(value))
        prop_values = ", ".join(formatted_sample_values)

        # If there wasn't an exact match with the user's search, we provide a hint that LLM can use an arbitrary value.
        if sample_count is None:
            return f"{prop_values} and many more distinct values."
        elif sample_count > len(sample_values):
            diff = sample_count - len(sample_values)
            return f"{prop_values} and {diff} more distinct value{'' if diff == 1 else 's'}."

        return prop_values

    def handle_incorrect_response(self, response: BaseModel) -> str:
        """
        No-op tool. Take a parsing error and return a response that the LLM can use to correct itself.
        Used to control a number of retries.
        """
        return response.model_dump_json()

    def get_tools(self) -> list:
        """Get tool signatures. Override in subclasses."""
        raise NotImplementedError

    def retrieve_entity_properties(self, entity: str, max_properties: int = 500) -> str:
        """
        Retrieve properties for an entity like person, session, or one of the groups.
        """
        if entity not in ("person", "session", *[group.group_type for group in self._groups]):
            return f"Entity {entity} does not exist in the taxonomy."

        if entity == "person":
            qs = PropertyDefinition.objects.filter(team=self._team, type=PropertyDefinition.Type.PERSON).values_list(
                "name", "property_type"
            )
            props = self._enrich_props_with_descriptions("person", qs)
        elif entity == "session":
            # Session properties are not in the DB.
            props = self._enrich_props_with_descriptions(
                "session",
                [
                    (prop_name, prop["type"])
                    for prop_name, prop in CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"].items()
                    if prop.get("type") is not None
                ],
            )
        else:
            group_type_index = next(
                (group.group_type_index for group in self._groups if group.group_type == entity), None
            )
            if group_type_index is None:
                return f"Group {entity} does not exist in the taxonomy."
            qs = PropertyDefinition.objects.filter(
                team=self._team, type=PropertyDefinition.Type.GROUP, group_type_index=group_type_index
            ).values_list("name", "property_type")[:max_properties]
            props = self._enrich_props_with_descriptions(entity, qs)

        if not props:
            return f"Properties do not exist in the taxonomy for the entity {entity}."

        return self._generate_properties_output(props)

    def retrieve_entity_property_values(self, entity: str, property_name: str) -> str:
        """Retrieve property values for an entity."""
        if entity not in self._entity_names:
            return f"The entity {entity} does not exist in the taxonomy. You must use one of the following: {', '.join(self._entity_names)}."

        if entity == "session":
            return self._retrieve_session_properties(property_name)
        if entity == "person":
            query = ActorsPropertyTaxonomyQuery(property=property_name, maxPropertyValues=25)
        elif entity == "event":
            query = ActorsPropertyTaxonomyQuery(property=property_name, maxPropertyValues=50)
        else:
            group_index = next((group.group_type_index for group in self._groups if group.group_type == entity), None)
            if group_index is None:
                return f"The entity {entity} does not exist in the taxonomy."
            query = ActorsPropertyTaxonomyQuery(
                group_type_index=group_index, property=property_name, maxPropertyValues=25
            )

        try:
            if query.group_type_index is not None:
                prop_type = PropertyDefinition.Type.GROUP
                group_type_index = query.group_type_index
            elif entity == "event":
                prop_type = PropertyDefinition.Type.EVENT
                group_type_index = None
            else:
                prop_type = PropertyDefinition.Type.PERSON
                group_type_index = None
            property_definition = PropertyDefinition.objects.get(
                team=self._team,
                name=property_name,
                type=prop_type,
                group_type_index=group_type_index,
            )
        except PropertyDefinition.DoesNotExist:
            return f"The property {property_name} does not exist in the taxonomy for the entity {entity}."

        response = ActorsPropertyTaxonomyQueryRunner(query, self._team).run(
            ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS
        )

        if not isinstance(response, CachedActorsPropertyTaxonomyQueryResponse):
            return f"The entity {entity} does not exist in the taxonomy."

        if not response.results:
            return f"Property values for {property_name} do not exist in the taxonomy for the entity {entity}."

        return self._format_property_values(
            response.results.sample_values,
            response.results.sample_count,
            format_as_string=property_definition.property_type in (PropertyType.String, PropertyType.Datetime),
        )

    def retrieve_event_or_action_properties(self, event_name_or_action_id: str | int) -> str:
        """
        Retrieve properties for an event.
        """
        try:
            response, verbose_name = self._retrieve_event_or_action_taxonomy(event_name_or_action_id)
        except Action.DoesNotExist:
            project_actions = Action.objects.filter(team__project_id=self._team.project_id, deleted=False)
            if not project_actions:
                return "No actions exist in the project."
            return f"Action {event_name_or_action_id} does not exist in the taxonomy. Verify that the action ID is correct and try again."
        if not isinstance(response, CachedEventTaxonomyQueryResponse):
            return "Properties have not been found."
        if not response.results:
            return f"Properties do not exist in the taxonomy for the {verbose_name}."
        # Intersect properties with their types.
        qs = PropertyDefinition.objects.filter(
            team=self._team, type=PropertyDefinition.Type.EVENT, name__in=[item.property for item in response.results]
        )
        property_to_type = {property_definition.name: property_definition.property_type for property_definition in qs}
        props = [
            (item.property, property_to_type.get(item.property))
            for item in response.results
            # Exclude properties that exist in the taxonomy, but don't have a type.
            if item.property in property_to_type
        ]

        if not props:
            return f"Properties do not exist in the taxonomy for the {verbose_name}."
        return self._generate_properties_output(self._enrich_props_with_descriptions("event", props))

    def retrieve_event_or_action_property_values(self, event_name_or_action_id: str | int, property_name: str) -> str:
        try:
            property_definition = PropertyDefinition.objects.get(
                team=self._team, name=property_name, type=PropertyDefinition.Type.EVENT
            )
        except PropertyDefinition.DoesNotExist:
            return f"The property {property_name} does not exist in the taxonomy."

        response, verbose_name = self._retrieve_event_or_action_taxonomy(event_name_or_action_id)
        if not isinstance(response, CachedEventTaxonomyQueryResponse):
            return f"The {verbose_name} does not exist in the taxonomy."
        if not response.results:
            return f"Property values for {property_name} do not exist in the taxonomy for the {verbose_name}."

        prop = next((item for item in response.results if item.property == property_name), None)
        if not prop:
            return f"The property {property_name} does not exist in the taxonomy for the {verbose_name}."

        return self._format_property_values(
            prop.sample_values,
            prop.sample_count,
            format_as_string=property_definition.property_type in (PropertyType.String, PropertyType.Datetime),
        )

    def _retrieve_session_properties(self, property_name: str) -> str:
        """
        Sessions properties example property values are hardcoded.
        """
        if property_name not in CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"]:
            return f"The property {property_name} does not exist in the taxonomy."

        sample_values: list[str | int | float]
        if property_name == "$channel_type":
            sample_values = cast(list[str | int | float], DEFAULT_CHANNEL_TYPES.copy())
            sample_count = len(sample_values)
            is_str = True
        elif (
            property_name in CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"]
            and "examples" in CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"][property_name]
        ):
            sample_values = CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"][property_name]["examples"]
            sample_count = None
            is_str = (
                CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"][property_name]["type"] == PropertyType.String
            )
        else:
            return f"Property values for {property_name} do not exist in the taxonomy for the session entity."

        return self._format_property_values(sample_values, sample_count, format_as_string=is_str)

    def _retrieve_event_or_action_taxonomy(self, event_name_or_action_id: str | int):
        is_event = isinstance(event_name_or_action_id, str)
        if is_event:
            query = EventTaxonomyQuery(event=event_name_or_action_id, maxPropertyValues=25)
            verbose_name = f"event {event_name_or_action_id}"
        else:
            query = EventTaxonomyQuery(actionId=event_name_or_action_id, maxPropertyValues=25)
            verbose_name = f"action with ID {event_name_or_action_id}"
        runner = EventTaxonomyQueryRunner(query, self._team)
        response = runner.run(ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS)
        return response, verbose_name

    def _generate_properties_output(self, props: list[tuple[str, str | None, str | None]]) -> str:
        """
        Generate the output format for properties. Can be overridden by subclasses.
        Default implementation uses XML format.
        """
        return self._generate_properties_xml(props)

    def _generate_properties_xml(self, children: list[tuple[str, str | None, str | None]]):
        import xml.etree.ElementTree as ET

        root = ET.Element("properties")
        property_type_to_tag = {}

        for name, property_type, description in children:
            # Do not include properties that are ambiguous.
            if property_type is None:
                continue
            if property_type not in property_type_to_tag:
                property_type_to_tag[property_type] = ET.SubElement(root, property_type)

            type_tag = property_type_to_tag[property_type]
            prop = ET.SubElement(type_tag, "prop")
            ET.SubElement(prop, "name").text = name
            if description:
                ET.SubElement(prop, "description").text = description

        return ET.tostring(root, encoding="unicode")

    def handle_tools(self, tool_name: str, tool_input: ToolInput) -> tuple[str, str]:
        """Handle tool execution and return (tool_id, result). Override in subclasses."""
        raise NotImplementedError


class TaxonomyAgentNode(Generic[State], TaxonomyNode):
    """Base node for taxonomy agents."""

    toolkit_class: type[TaxonomyAgentToolkit] | None = None

    def __init__(self, team: Team, user: User, toolkit_class: type[TaxonomyAgentToolkit] | None = None):
        super().__init__(team, user)
        toolkit_cls = toolkit_class or self.toolkit_class or TaxonomyAgentToolkit
        self._toolkit = toolkit_cls(team=team)

    def _get_system_prompt(self, state: State) -> str:
        """Get the system prompt for this node. Override in subclasses."""
        raise NotImplementedError


class TaxonomyAgentToolsNode(Generic[State], TaxonomyNode):
    """Base tools node for taxonomy agents."""

    toolkit_class: type[TaxonomyAgentToolkit] | None = None

    def __init__(self, team: Team, user: User, toolkit_class: type[TaxonomyAgentToolkit] | None = None):
        super().__init__(team, user)
        toolkit_cls = toolkit_class or self.toolkit_class or TaxonomyAgentToolkit
        self._toolkit = toolkit_cls(team=team)

    def router(self, state: State) -> str:
        """Route based on the state. Override in subclasses."""
        return "end"


class TaxonomyAgent(Generic[State]):
    """Taxonomy agent that can be configured with different node classes."""

    def __init__(
        self,
        team: Team,
        user: User,
        loop_node_class: type[TaxonomyAgentNode],
        tools_node_class: type[TaxonomyAgentToolsNode],
    ):
        self._team = team
        self._user = user
        self._loop_node_class = loop_node_class
        self._tools_node_class = tools_node_class

        # Extract the State type from the generic parameter
        state_class = self._get_state_class()
        self._graph = StateGraph(state_class)
        self._has_start_node = False

    def _get_state_class(self) -> type:
        """Extract the State type from the class's generic parameters."""
        # Check if this class has generic arguments
        if hasattr(self.__class__, "__orig_bases__"):
            for base in self.__class__.__orig_bases__:
                if get_origin(base) is TaxonomyAgent:
                    args = get_args(base)
                    if args:
                        return args[0]  # State is the first argument

        # No generic type found - this shouldn't happen in proper usage
        raise ValueError(
            f"Could not determine state type for {self.__class__.__name__}. "
            "Make sure to inherit from TaxonomyAgent with a specific state type, "
            "e.g., TaxonomyAgent[FilterOptionsState]"
        )

    def add_edge(self, from_node: str, to_node: str):
        if from_node == "START":
            self._has_start_node = True
        self._graph.add_edge(from_node, to_node)
        return self

    def add_node(self, node: str, action):
        self._graph.add_node(node, action)
        return self

    def add_conditional_edges(self, node: str, router, path_map: dict):
        self._graph.add_conditional_edges(node, router, path_map)
        return self

    def compile(self, checkpointer=None):
        if not self._has_start_node:
            raise ValueError("Start node not added to the graph")
        return self._graph.compile(checkpointer=checkpointer)

    def compile_full_graph(self, checkpointer: DjangoCheckpointer | None = None):
        """Compile a complete taxonomy graph."""
        return self.add_taxonomy_generator().compile(checkpointer=checkpointer)

    def add_taxonomy_generator(self, next_node: AssistantNodeName = AssistantNodeName.END):
        """Add the taxonomy generator nodes to the graph."""
        builder = self._graph
        self._has_start_node = True

        # Add the main loop node
        loop_node = self._loop_node_class(self._team, self._user)
        builder.add_node(TaxonomyNodeName.LOOP_NODE, loop_node)
        builder.add_edge(AssistantNodeName.START, TaxonomyNodeName.LOOP_NODE)

        # Add the tools node
        tools_node = self._tools_node_class(self._team, self._user)
        builder.add_node(TaxonomyNodeName.TOOLS_NODE, tools_node)
        builder.add_edge(TaxonomyNodeName.LOOP_NODE, TaxonomyNodeName.TOOLS_NODE)

        # Add conditional edges based on the tools node's router
        builder.add_conditional_edges(
            TaxonomyNodeName.TOOLS_NODE,
            tools_node.router,
            {
                "continue": TaxonomyNodeName.LOOP_NODE,
                "end": next_node,
            },
        )

        return self
