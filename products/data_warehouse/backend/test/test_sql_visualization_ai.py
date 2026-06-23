from types import SimpleNamespace
from typing import cast

from unittest import mock

from posthog.models.team import Team
from posthog.models.user import User

from products.data_warehouse.backend.sql_visualization_ai import (
    SQL_VISUALIZATION_AI_TIMEOUT_SECONDS,
    SQLVisualizationGenerationPayload,
    build_fallback_sql_visualization,
    generate_sql_visualization,
)

SQL_VISUALIZATION_PAYLOAD: SQLVisualizationGenerationPayload = {
    "query": "select event, count() from events group by event",
    "prompt": "make a chart",
    "columns": [
        {
            "name": "event",
            "type": "String",
            "semanticType": "nominal",
            "sampleValues": ["$pageview"],
        },
        {
            "name": "count",
            "type": "UInt64",
            "semanticType": "quantitative",
            "sampleValues": [123],
        },
    ],
    "fields": [
        {
            "field": "event",
            "sourceColumn": "event",
            "label": "event",
            "type": "String",
            "semanticType": "nominal",
        },
        {
            "field": "count",
            "sourceColumn": "count()",
            "label": "count",
            "type": "UInt64",
            "semanticType": "quantitative",
        },
    ],
    "sampleRows": [{"event": "$pageview", "count": 123}],
    "rowCount": 1,
}


class FailingStructuredModel:
    def invoke(self, *args: object, **kwargs: object) -> object:
        raise RuntimeError("AI generation failed")


class FailingChatModel:
    def with_structured_output(self, *args: object, **kwargs: object) -> FailingStructuredModel:
        return FailingStructuredModel()


def test_build_fallback_sql_visualization_uses_dimension_and_quantitative_fields() -> None:
    result = build_fallback_sql_visualization(SQL_VISUALIZATION_PAYLOAD)

    assert result.spec["data"] == {"name": "posthog_results"}
    assert result.spec["mark"] == "bar"
    assert result.spec["encoding"]["x"]["field"] == "event"
    assert result.spec["encoding"]["x"]["sort"] == "-y"
    assert result.spec["encoding"]["y"]["field"] == "count"
    assert result.warnings == ["AI generation failed, so a basic chart was generated from the result shape."]


def test_build_fallback_sql_visualization_honors_pie_prompt() -> None:
    result = build_fallback_sql_visualization(
        {
            **SQL_VISUALIZATION_PAYLOAD,
            "prompt": "Create the best chart suited for this data. make it colorful. make it a pie chart",
            "rowCount": 50,
        }
    )

    assert result.spec["mark"] == "arc"
    assert result.spec["encoding"]["theta"]["field"] == "count"
    assert result.spec["encoding"]["color"]["field"] == "event"
    assert result.warnings == [
        "AI generation failed, so a basic chart was generated from the result shape.",
        "Pie charts can be hard to read with many categories.",
    ]


def test_generate_sql_visualization_falls_back_when_ai_generation_fails() -> None:
    with mock.patch(
        "products.data_warehouse.backend.sql_visualization_ai.MaxChatOpenAI",
        return_value=FailingChatModel(),
    ) as max_chat_openai:
        result = generate_sql_visualization(
            payload=SQL_VISUALIZATION_PAYLOAD,
            team=cast(Team, SimpleNamespace(id=1)),
            user=cast(User, SimpleNamespace(distinct_id="user-1")),
            trace_id="trace-1",
        )

    assert result.spec["mark"] == "bar"
    assert result.spec["encoding"]["x"]["field"] == "event"
    assert result.spec["encoding"]["y"]["field"] == "count"
    assert max_chat_openai.call_args.kwargs["timeout"] == SQL_VISUALIZATION_AI_TIMEOUT_SECONDS
    assert max_chat_openai.call_args.kwargs["max_retries"] == 0
