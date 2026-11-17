import uuid
from datetime import timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.utils import timezone

from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor

from posthog.models.ai_events.test_util import bulk_create_ai_events

from products.ai_observability.backend.logic.eval_suggestions import call_review_queries
from products.ai_observability.backend.logic.eval_suggestions.profile_queries import ProfileWindow


class TestCallReviewQueries(ClickhouseTestMixin, BaseTest):
    def test_stored_copies_of_a_call_count_and_fill_each_cap_once(self) -> None:
        end = timezone.now() - timedelta(minutes=30)
        bulk_create_ai_events(
            [
                {
                    "event": "$ai_generation",
                    "event_uuid": event_uuid,
                    "distinct_id": "user-1",
                    "team_id": self.team.pk,
                    "timestamp": end - timedelta(hours=1),
                    "properties": {
                        "$ai_trace_id": f"trace-{index}",
                        "$ai_model": "example-model-mini",
                        "$ai_prompt_name": "support-reply",
                        "$ai_input": [{"role": "user", "content": "Where is my refund?"}],
                        "$ai_output_choices": [{"role": "assistant", "content": "It was sent."}],
                    },
                }
                for index, event_uuid in enumerate([str(uuid.uuid4()) for _ in range(3)])
                for _copy in range(2)
            ]
        )
        window = ProfileWindow(start=end - timedelta(days=1), end=end)

        call_types = call_review_queries.load_call_types(self.team, window, 1000)
        with patch.object(call_review_queries, "CANDIDATES_PER_CALL_TYPE", 2):
            calls = call_review_queries.load_review_calls(self.team, window, 1000, call_types)

        assert [(call_type.key, call_type.calls) for call_type in call_types] == [("prompt_name:support-reply", 3)]
        assert len({call.event_uuid for call in calls}) == len(calls) == 2

    def test_a_snippet_counts_the_generations_it_matches_and_those_of_its_call_type(self) -> None:
        end = timezone.now() - timedelta(minutes=30)
        summarizer = "You summarize one trace for an engineer."
        # Another call type quotes the summarizer's prompt after a prompt of its own.
        reviewer = f"You review summaries. The summarizer was told: {summarizer}"
        bulk_create_ai_events(
            [
                {
                    "event": "$ai_generation",
                    "distinct_id": "user-1",
                    "team_id": self.team.pk,
                    "timestamp": end - timedelta(hours=1),
                    "properties": {
                        "$ai_trace_id": f"trace-{system[:3]}-{index}",
                        "$ai_model": "example-model-mini",
                        "$ai_input": [{"role": "system", "content": system}, {"role": "user", "content": "A trace"}],
                    },
                }
                for system, count in ((summarizer, 3), (reviewer, 2))
                for index in range(count)
            ]
        )
        window = ProfileWindow(start=end - timedelta(days=1), end=end)
        call_types = call_review_queries.load_call_types(self.team, window, 1000)
        [summarizer_type] = [c for c in call_types if c.calls == 3]

        matches = call_review_queries.snippet_matches(
            self.team, window, 1000, summarizer_type, ["summarize one trace", "You review summaries", "absent text"]
        )

        assert [(m.matched, m.in_call_type) for m in matches] == [(5, 3), (2, 0), (0, 0)]


def test_the_calls_query_runs_its_candidate_subquery_once_across_shards() -> None:
    ops: list[ast.CompareOperationOp] = []

    class Subqueries(TraversingVisitor):
        def visit_compare_operation(self, node: ast.CompareOperation) -> None:
            if isinstance(node.right, ast.SelectQuery):
                ops.append(node.op)
            super().visit_compare_operation(node)

    Subqueries().visit(call_review_queries._calls_query())

    assert ops == [ast.CompareOperationOp.GlobalIn]
