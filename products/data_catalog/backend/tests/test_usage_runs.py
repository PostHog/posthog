from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from products.data_catalog.backend.facade.contracts import AdjustedRun, MetricRunCounts, UsageSnapshotPayload
from products.data_catalog.backend.facade.enums import FetchOutcome, JudgeRelation, UsageSnapshotStatus
from products.data_catalog.backend.logic.metrics import upsert_metric
from products.data_catalog.backend.logic.usage_runs import collect_metric_runs_into_snapshot
from products.data_catalog.backend.logic.usage_snapshots import payload_from_json, payload_to_json
from products.data_catalog.backend.models import Metric, UsageSnapshot


class TestCollectMetricRuns(ClickhouseTestMixin, BaseTest):
    def _run(self, metric_id: object, source: str, distinct_id: str, **overrides: Any) -> None:
        timestamp = overrides.pop("timestamp", self.window_end - timedelta(days=1))
        project = overrides.pop("project", str(self.team.uuid))
        _create_event(
            team=self.team,
            event="data catalog metric run",
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties={"metric_id": str(metric_id), "source": source, "$groups": {"project": project}, **overrides},
        )

    def test_counts_agent_runs_by_surface_with_scouts_apart_and_keeps_other_sections(self) -> None:
        self.window_end = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
        mrr = upsert_metric(team=self.team, user=self.user, name="mrr", description="Monthly revenue")
        retired = upsert_metric(team=self.team, user=self.user, name="old", description="Retired metric")
        Metric.objects.for_team(self.team.id).filter(id=retired.id).update(deleted=True)

        self._run(mrr.id, "web", "u1")
        self._run(mrr.id, "api", "u8")
        self._run(mrr.id, "mcp", "u1")
        self._run(mrr.id, "mcp", "u2")
        self._run(mrr.id, "posthog_ai", "u7")
        self._run(mrr.id, "self_driving", "u3")
        self._run(mrr.id, "self_driving", "u3")
        self._run(mrr.id, "mcp", "u4", was_impersonated=True)
        self._run(mrr.id, "mcp", "u5", timestamp=self.window_end - timedelta(days=40))
        self._run(mrr.id, "mcp", "u6", project="00000000-0000-0000-0000-000000000000")
        self._run(retired.id, "mcp", "u1")
        flush_persons_and_events()

        kept = AdjustedRun(
            metric_id=mrr.id,
            fetch_outcome=FetchOutcome.SILENT,
            relation=JudgeRelation.SERVES,
            intent="monthly revenue",
            sql="select sum(amount) from charges",
            reasoning="Same measure.",
            occurred_at=self.window_end - timedelta(days=2),
            session_id=None,
            is_scout=False,
        )
        snapshot = UsageSnapshot.objects.for_team(self.team.id).create(
            team=self.team,
            status=UsageSnapshotStatus.COMPUTING.value,
            window_start=self.window_end - timedelta(days=28),
            window_end=self.window_end,
            payload=payload_to_json(UsageSnapshotPayload(adjusted_runs=[kept])),
        )

        rows = collect_metric_runs_into_snapshot(
            team_id=self.team.id, snapshot_id=snapshot.id, telemetry_team_id=self.team.id
        )

        snapshot.refresh_from_db()
        payload = payload_from_json(snapshot.payload)
        assert rows == 1
        assert payload.metric_runs == [
            MetricRunCounts(
                metric_id=mrr.id,
                direct_runs={"mcp": 2, "posthog_ai": 1},
                direct_people=3,
                scout_runs=2,
                source_insight_dashboard_runs=0,
                source_insight_insight_runs=0,
            )
        ]
        assert payload.adjusted_runs == [kept]
