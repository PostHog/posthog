from datetime import timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from posthog.schema import SuggestedQuestionsQuery

from posthog.hogql_queries.ai.suggested_questions_query_runner import SuggestedQuestionsQueryRunner


@override_settings(IN_UNIT_TESTING=True)
class TestSuggestedQuestionsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    @snapshot_clickhouse_queries
    @patch(
        "posthog.hogql_queries.ai.suggested_questions_query_runner.hit_openai",
        return_value=("Lorem ipsum. QUESTIONS:\nHow? 78\n\nWhy? 91", 21, 37),
    )
    def test_suggested_questions_hit_openai(self, hit_openai_mock):
        results = SuggestedQuestionsQueryRunner(team=self.team, query=SuggestedQuestionsQuery()).calculate()
        hit_openai_mock.assert_called_once()
        self.assertEqual(results.questions, ["Why?", "How?"])

    def test_is_stale(self):
        date = timezone.now()
        runner = SuggestedQuestionsQueryRunner(team=self.team, query=SuggestedQuestionsQuery())
        self.assertFalse(runner._is_stale(last_refresh=date, lazy=False))
        self.assertFalse(runner._is_stale(last_refresh=date, lazy=True))
        self.assertFalse(runner._is_stale(last_refresh=date - timedelta(days=2, hours=23, minutes=59), lazy=False))
        self.assertFalse(runner._is_stale(last_refresh=date - timedelta(days=2, hours=23, minutes=59), lazy=True))
        self.assertTrue(runner._is_stale(last_refresh=date - timedelta(days=3), lazy=True))
        self.assertTrue(runner._is_stale(last_refresh=date - timedelta(days=3), lazy=False))
