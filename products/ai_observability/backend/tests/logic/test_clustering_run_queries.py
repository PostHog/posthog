import json
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.models.event.util import bulk_create_events

from products.ai_observability.backend.facade.clustering_contracts import ClusteringRunContext
from products.ai_observability.backend.logic.clustering.execution import scope_key
from products.ai_observability.backend.logic.clustering.run_queries import (
    count_eligible_evaluations,
    count_ready_items,
    count_trace_candidates,
)


class TestClusteringRunQueries(ClickhouseTestMixin, BaseTest):
    def context(self, analysis_level="trace"):
        return ClusteringRunContext(
            active=True,
            job_id="0192f200-0000-7000-8000-000000000001",
            job_name="Production",
            analysis_level=analysis_level,
            event_filters=[{"type": "event", "key": "environment", "operator": "exact", "value": "production"}],
            minimum=10,
            lookback_days=7,
            user_id=self.user.id,
        )

    @parameterized.expand([("trace", 10), ("generation", 1), ("evaluation", 1)])
    def test_candidates_are_distinct_filtered_items_capped_at_the_minimum(self, analysis_level, expected):
        start = datetime(2026, 11, 1, tzinfo=UTC)
        events = [("$ai_span", f"trace-{index}", "production", start) for index in range(12)] + [
            ("$ai_generation", "trace-0", "production", start),
            ("$ai_generation", "trace-0", "production", start),
            ("$ai_generation", "test-trace", "test", start),
            ("$ai_generation", "old-trace", "production", start - timedelta(days=1)),
            ("$ai_generation", "", "production", start),
            ("$pageview", "non-ai", "production", start),
            ("$ai_evaluation", "evaluation-trace", "production", start),
            ("$ai_evaluation", "test-evaluation-trace", "test", start),
        ]
        bulk_create_events(
            [
                {
                    "team": self.team,
                    "event": event,
                    "distinct_id": "user",
                    "timestamp": timestamp,
                    "properties": {"$ai_trace_id": trace_id, "environment": environment},
                }
                for event, trace_id, environment, timestamp in events
            ]
        )
        count = count_eligible_evaluations if analysis_level == "evaluation" else count_trace_candidates
        assert count(self.team.id, self.context(analysis_level), start, start + timedelta(days=1)) == expected

    def test_prepared_items_exclude_embeddings_from_a_previous_job_scope(self):
        start = datetime(2026, 11, 1, tzinfo=UTC)
        context = self.context()
        current = scope_key(context.analysis_level, context.event_filters)
        previous = scope_key(context.analysis_level, [])
        sync_execute(
            """INSERT INTO writable_posthog_document_embeddings_text_embedding_3_large_3072
            (team_id, product, document_type, rendering, document_id, timestamp, inserted_at, content, embedding, metadata)
            VALUES""",
            [
                (
                    self.team.id,
                    "llm-analytics",
                    "llm-trace-summary-detailed",
                    "detailed",
                    f"{item}::{context.job_id}::{scope}",
                    start,
                    start,
                    "Example",
                    [0.1] * 3072,
                    json.dumps({"job_id": context.job_id, "job_scope": scope}),
                )
                for item, scope in [("old", previous), ("shared", previous), ("shared", current), ("new", current)]
            ],
        )
        assert count_ready_items(self.team.id, context, start, start + timedelta(days=1)) == 2
