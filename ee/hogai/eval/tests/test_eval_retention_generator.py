from collections.abc import Callable
from datetime import datetime
from typing import cast

import pytest
from langgraph.graph.state import CompiledStateGraph

from ee.hogai.assistant import AssistantGraph
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from posthog.schema import (
    AssistantRetentionQuery,
    HumanMessage,
    RetentionEntity,
    VisualizationMessage,
)


@pytest.fixture
def call_node(team, runnable_config) -> Callable[[str, str], AssistantRetentionQuery]:
    graph: CompiledStateGraph = (
        AssistantGraph(team)
        .add_edge(AssistantNodeName.START, AssistantNodeName.RETENTION_GENERATOR)
        .add_retention_generator(AssistantNodeName.END)
        .compile()
    )

    def callable(query: str, plan: str) -> AssistantRetentionQuery:
        state = graph.invoke(
            AssistantState(messages=[HumanMessage(content=query)], plan=plan),
            runnable_config,
        )
        message = cast(VisualizationMessage, AssistantState.model_validate(state).messages[-1])
        answer = message.answer
        assert isinstance(answer, AssistantRetentionQuery), "Expected AssistantRetentionQuery"
        return answer

    return callable


def test_node_replaces_equals_with_contains(call_node):
    query = "Show file upload retention after signup for users with name John"
    plan = """Target event:
    - signed_up

    Returning event:
    - file_uploaded

    Filters:
        - property filter 1:
            - person
            - name
            - equals
            - John
    """
    actual_output = call_node(query, plan).model_dump_json(exclude_none=True)
    assert "exact" not in actual_output
    assert "icontains" in actual_output
    assert "John" not in actual_output
    assert "john" in actual_output


def test_basic_retention_structure(call_node):
    query = "Show retention for users who signed up"
    plan = """Target Event:
    - signed_up

    Returning Event:
    - file_uploaded
    """
    actual_output = call_node(query, plan)
    assert actual_output.retentionFilter is not None
    assert actual_output.retentionFilter.targetEntity == RetentionEntity(
        id="signed_up", type="events", name="signed_up", order=0
    )
    assert actual_output.retentionFilter.returningEntity == RetentionEntity(
        id="file_uploaded", type="events", name="file_uploaded", order=0
    )


def test_current_date(call_node):
    query = "Show retention for users who signed up in this January?"
    plan = """Target Event:
    - signed_up

    Returning Event:
    - file_uploaded
    """
    date_range = call_node(query, plan).dateRange
    assert date_range is not None
    year = str(datetime.now().year)
    assert (date_range.date_from and year in date_range.date_from) or (
        date_range.date_to and year in date_range.date_to
    )
