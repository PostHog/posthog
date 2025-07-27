from collections.abc import Sequence
from typing import Optional, TypeVar, Union

from jsonref import replace_refs
from langchain_core.messages import (
    HumanMessage as LangchainHumanMessage,
    merge_message_runs,
)

from ee.hogai.utils.types import AssistantMessageUnion
from posthog.schema import (
    AssistantMessage,
    AssistantToolCallMessage,
    HumanMessage,
    MaxUIContext,
    VisualizationMessage,
)
from posthog.schema import MaxEventContext, TeamTaxonomyQuery, CachedTeamTaxonomyQueryResponse
from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP
from posthog.models import Team
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner
import xml.etree.ElementTree as ET


def remove_line_breaks(line: str) -> str:
    return line.replace("\n", " ")


def filter_and_merge_messages(
    messages: Sequence[AssistantMessageUnion],
    entity_filter: Union[tuple[type[AssistantMessageUnion], ...], type[AssistantMessageUnion]] = (
        AssistantMessage,
        VisualizationMessage,
    ),
) -> list[AssistantMessageUnion]:
    """
    Filters and merges the message history to be consumable by agents. Returns human and AI messages.
    """
    stack: list[LangchainHumanMessage] = []
    filtered_messages: list[AssistantMessageUnion] = []

    def _merge_stack(stack: list[LangchainHumanMessage]) -> list[HumanMessage]:
        return [
            HumanMessage(content=langchain_message.content, id=langchain_message.id)
            for langchain_message in merge_message_runs(stack)
        ]

    for message in messages:
        if isinstance(message, HumanMessage):
            stack.append(LangchainHumanMessage(content=message.content, id=message.id))
        elif isinstance(message, entity_filter):
            if stack:
                filtered_messages += _merge_stack(stack)
                stack = []
            filtered_messages.append(message)

    if stack:
        filtered_messages += _merge_stack(stack)

    return filtered_messages


T = TypeVar("T", bound=AssistantMessageUnion)


def find_last_message_of_type(messages: Sequence[AssistantMessageUnion], message_type: type[T]) -> Optional[T]:
    return next((msg for msg in reversed(messages) if isinstance(msg, message_type)), None)


def slice_messages_to_conversation_start(
    messages: Sequence[AssistantMessageUnion], start_id: Optional[str] = None
) -> Sequence[AssistantMessageUnion]:
    result = []
    for msg in messages:
        result.append(msg)
        if msg.id == start_id:
            break
    return result


def dereference_schema(schema: dict) -> dict:
    new_schema: dict = replace_refs(schema, proxies=False, lazy_load=False)
    if "$defs" in new_schema:
        new_schema.pop("$defs")
    return new_schema


def find_start_message(messages: Sequence[AssistantMessageUnion], start_id: str | None = None) -> HumanMessage | None:
    for msg in messages:
        if isinstance(msg, HumanMessage) and msg.id == start_id:
            return msg
    return None


def should_output_assistant_message(candidate_message: AssistantMessageUnion) -> bool:
    """
    This is used to filter out messages that are not useful for the user.
    Filter out tool calls without a UI payload and empty assistant messages.
    """
    if isinstance(candidate_message, AssistantToolCallMessage) and candidate_message.ui_payload is None:
        return False

    if isinstance(candidate_message, AssistantMessage) and not candidate_message.content:
        return False

    return True


def find_last_ui_context(messages: Sequence[AssistantMessageUnion]) -> MaxUIContext | None:
    """Returns the last recorded UI context from all messages."""
    for message in reversed(messages):
        if isinstance(message, HumanMessage) and message.ui_context is not None:
            return message.ui_context
    return None


def format_events_prompt(events_in_context: list[MaxEventContext], team: Team) -> str:
    response = TeamTaxonomyQueryRunner(TeamTaxonomyQuery(), team).run(
        ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS
    )

    if not isinstance(response, CachedTeamTaxonomyQueryResponse):
        raise ValueError("Failed to generate events prompt.")

    events: list[str] = [
        # Add "All events" to the mapping
        "All events",
    ]
    for item in response.results:
        if len(response.results) > 25 and item.count <= 3:
            continue
        if event_core_definition := CORE_FILTER_DEFINITIONS_BY_GROUP["events"].get(item.event):
            if event_core_definition.get("system") or event_core_definition.get("ignored_in_assistant"):
                continue  # Skip system or ignored events
        events.append(item.event)
    event_to_description: dict[str, str] = {}
    for event in events_in_context:
        if event.name and event.name not in events:
            events.append(event.name)
        if event.name and event.description:
            event_to_description[event.name] = event.description

    # Create a set of event names from context for efficient lookup
    context_event_names = {event.name for event in events_in_context if event.name}

    root = ET.Element("defined_events")
    for event_name in events:
        event_tag = ET.SubElement(root, "event")
        name_tag = ET.SubElement(event_tag, "name")
        name_tag.text = event_name
        if event_core_definition := CORE_FILTER_DEFINITIONS_BY_GROUP["events"].get(event_name):
            # Only skip if it's not in context (context events should always be included)
            if event_name not in context_event_names and (
                event_core_definition.get("system") or event_core_definition.get("ignored_in_assistant")
            ):
                continue  # Skip irrelevant events but keep events the user has added to the context
            if description := event_core_definition.get("description"):
                desc_tag = ET.SubElement(event_tag, "description")
                if label := event_core_definition.get("label_llm") or event_core_definition.get("label"):
                    desc_tag.text = f"{label}. {description}"
                else:
                    desc_tag.text = description
                desc_tag.text = remove_line_breaks(desc_tag.text)
        elif event_name in event_to_description:
            desc_tag = ET.SubElement(event_tag, "description")
            desc_tag.text = event_to_description[event_name]
            desc_tag.text = remove_line_breaks(desc_tag.text)
    return ET.tostring(root, encoding="unicode")
