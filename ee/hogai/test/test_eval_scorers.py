import json

from django.test import SimpleTestCase

from parameterized import parameterized
from pydantic import BaseModel

from posthog.schema import AssistantFunnelsQuery, AssistantRetentionQuery, AssistantTrendsQuery, NodeKind

from ee.hogai.eval.scorers import MAX_JUDGE_JSON_SCHEMA_CHARS, build_judge_json_schema


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
