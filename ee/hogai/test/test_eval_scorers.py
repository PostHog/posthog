import json

from django.test import SimpleTestCase

from parameterized import parameterized
from pydantic import BaseModel

from posthog.schema import (
    AssistantFunnelsQuery,
    AssistantMessage,
    AssistantRetentionQuery,
    AssistantToolCall,
    AssistantTrendsQuery,
    NodeKind,
)

from ee.hogai.eval.scorers import MAX_JUDGE_JSON_SCHEMA_CHARS, ToolRelevance, build_judge_json_schema


class TestBuildJudgeJsonSchema(SimpleTestCase):
    @parameterized.expand(
        [
            (NodeKind.TRENDS_QUERY, AssistantTrendsQuery),
            (NodeKind.FUNNELS_QUERY, AssistantFunnelsQuery),
            (NodeKind.RETENTION_QUERY, AssistantRetentionQuery),
        ]
    )
    def test_insight_query_schema_fits_the_judge_budget(
        self, query_kind: NodeKind, query_model: type[BaseModel]
    ) -> None:
        json_schema_str = build_judge_json_schema(query_kind, query_model)

        self.assertLessEqual(len(json_schema_str), MAX_JUDGE_JSON_SCHEMA_CHARS)
        self.assertEqual(json.loads(json_schema_str)["title"], query_model.__name__)


class TestToolRelevance(SimpleTestCase):
    def test_returns_zero_when_the_assistant_makes_no_tool_calls(self) -> None:
        expected = AssistantToolCall(id="expected", name="create_insight", args={"query": "pageviews"})

        score = ToolRelevance(semantic_similarity_args=set())._run_eval_sync(AssistantMessage(content=""), expected)

        self.assertEqual(score.score, 0.0)

    def test_uses_the_best_matching_tool_call(self) -> None:
        expected = AssistantToolCall(id="expected", name="create_insight", args={"query": "pageviews"})
        output = AssistantMessage(
            content="",
            tool_calls=[
                AssistantToolCall(id="wrong-tool", name="search", args={"query": "pageviews"}),
                AssistantToolCall(id="partial-match", name="create_insight", args={"query": "users"}),
                AssistantToolCall(id="full-match", name="create_insight", args={"query": "pageviews"}),
            ],
        )

        score = ToolRelevance(semantic_similarity_args=set())._run_eval_sync(output, expected)

        self.assertEqual(score.score, 1.0)
