from datetime import UTC, datetime, timedelta
from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.team import Team

from products.data_catalog.backend.facade.contracts import (
    AdjustedRun,
    MetricRunCounts,
    TableSource,
    TopicDefinition,
    UsageSnapshotPayload,
)
from products.data_catalog.backend.facade.enums import JudgeRelation, UsageSnapshotStatus
from products.data_catalog.backend.logic.metrics import upsert_metric
from products.data_catalog.backend.logic.usage_snapshots import (
    SCAN_STOPPED_MESSAGE,
    UsageReader,
    payload_to_json,
    visible_payload,
)
from products.data_catalog.backend.models import Metric, UsageSnapshot

_FLAG = "products.data_catalog.backend.logic.usage_snapshots.posthoganalytics.feature_enabled"
_WINDOW_END = datetime(2026, 10, 26, tzinfo=UTC)


def _adjusted(metric_id: UUID, *, is_scout: bool = False, sql: str = "select count() from events") -> AdjustedRun:
    return AdjustedRun(
        metric_id=metric_id,
        read_metric_first=False,
        relation=JudgeRelation.SERVES,
        intent="weekly signups",
        sql=sql,
        reasoning="Same event and aggregate.",
        occurred_at=_WINDOW_END - timedelta(days=1),
        session_id=None,
        is_scout=is_scout,
    )


_VISIBLE = UUID("00000000-0000-0000-0000-000000000001")
_HIDDEN = UUID("00000000-0000-0000-0000-000000000002")


def _counts(metric_id: UUID) -> MetricRunCounts:
    return MetricRunCounts(metric_id=metric_id, direct_runs={"web": 1}, direct_people=1, scout_runs=0)


class TestVisiblePayload(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_denied_tables_keeps_every_query", frozenset(), "select sum(amount) from billing", True),
            ("query_over_a_denied_table", frozenset({"billing"}), "select sum(amount) from billing", False),
            ("query_over_another_table", frozenset({"billing"}), "select count() from events", True),
            ("unparseable_query_with_denied_tables", frozenset({"billing"}), "select count( from", False),
            (
                "cut_query_with_denied_tables",
                frozenset({"billing"}),
                "select count() from events where " + "x = 1 and " * 600 + "1",
                False,
            ),
        ]
    )
    def test_reader_sees_only_visible_metrics_and_allowed_sql(
        self, _name: str, denied: frozenset[str], sql: str, kept: bool
    ) -> None:
        payload = UsageSnapshotPayload(
            metric_runs=[_counts(_VISIBLE), _counts(_HIDDEN)],
            adjusted_runs=[_adjusted(_VISIBLE, sql=sql), _adjusted(_HIDDEN)],
        )

        visible = visible_payload(payload, UsageReader(visible_metric_ids=frozenset({_VISIBLE}), denied_tables=denied))

        assert [counts.metric_id for counts in visible.metric_runs or []] == [_VISIBLE]
        assert [run.metric_id for run in visible.adjusted_runs or []] == ([_VISIBLE] if kept else [])

    def test_reader_does_not_see_a_source_over_a_denied_table(self) -> None:
        payload = UsageSnapshotPayload(
            table_sources=[
                TableSource(name="billing", sessions=3, people=2),
                TableSource(name="revenue_daily", sessions=2, people=1),
            ]
        )

        visible = visible_payload(
            payload, UsageReader(visible_metric_ids=frozenset(), denied_tables=frozenset({"billing"}))
        )

        assert [source.name for source in visible.table_sources or []] == ["revenue_daily"]

    @parameterized.expand([("open_reader", frozenset(), 1), ("reader_with_a_denied_table", frozenset({"billing"}), 0)])
    def test_topic_titles_reach_only_readers_without_denied_tables(
        self, _name: str, denied: frozenset[str], kept: int
    ) -> None:
        payload = UsageSnapshotPayload(topic_definitions=[TopicDefinition(title="Payroll", description="Salaries.")])

        visible = visible_payload(payload, UsageReader(visible_metric_ids=frozenset(), denied_tables=denied))

        assert len(visible.topic_definitions or []) == kept


class TestUsageSnapshotAPI(APIBaseTest):
    def _snapshot(
        self,
        *,
        team: Team | None = None,
        snapshot_status: UsageSnapshotStatus = UsageSnapshotStatus.DONE,
        computed_at: datetime | None = _WINDOW_END,
        payload: UsageSnapshotPayload | None = None,
    ) -> UsageSnapshot:
        team = team or self.team
        return UsageSnapshot.objects.for_team(team.id).create(
            team=team,
            status=snapshot_status.value,
            window_start=_WINDOW_END - timedelta(days=28),
            window_end=_WINDOW_END,
            computed_at=computed_at,
            payload=payload_to_json(payload or UsageSnapshotPayload()),
        )

    @parameterized.expand([("latest", "data_catalog/usage/latest/"), ("metric", "data_catalog/metrics/mrr/usage/")])
    def test_usage_endpoints_404_while_flag_is_off(self, _name: str, path: str) -> None:
        upsert_metric(team=self.team, user=self.user, name="mrr", description="Monthly revenue")
        self._snapshot()
        with patch(_FLAG, return_value=False):
            response = self.client.get(f"/api/projects/{self.team.id}/{path}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_latest_returns_newest_finished_snapshot_of_the_team(self) -> None:
        url = f"/api/projects/{self.team.id}/data_catalog/usage/latest/"
        with patch(_FLAG, return_value=True):
            assert self.client.get(url).status_code == status.HTTP_404_NOT_FOUND

            self._snapshot(computed_at=_WINDOW_END - timedelta(days=7))
            newest = self._snapshot()
            self._snapshot(snapshot_status=UsageSnapshotStatus.COMPUTING, computed_at=None)
            self._snapshot(snapshot_status=UsageSnapshotStatus.ERROR, computed_at=_WINDOW_END + timedelta(days=1))
            other_team = Team.objects.create(organization=self.organization, name="Other")
            self._snapshot(team=other_team, computed_at=_WINDOW_END + timedelta(days=2))

            response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["id"] == str(newest.id)
        assert response.json()["payload"]["metric_runs"] is None

    def test_metric_usage_returns_only_that_metrics_slice(self) -> None:
        mrr = upsert_metric(team=self.team, user=self.user, name="mrr", description="Monthly revenue")
        arr = upsert_metric(team=self.team, user=self.user, name="arr", description="Annual revenue")
        self._snapshot(
            payload=UsageSnapshotPayload(
                metric_runs=[
                    MetricRunCounts(
                        metric_id=mrr.id,
                        direct_runs={"web": 3, "mcp": 5},
                        direct_people=4,
                        scout_runs=120,
                    ),
                    MetricRunCounts(
                        metric_id=arr.id,
                        direct_runs={"web": 9},
                        direct_people=1,
                        scout_runs=0,
                    ),
                ],
                adjusted_runs=[
                    _adjusted(mrr.id),
                    _adjusted(mrr.id, is_scout=True),
                    _adjusted(arr.id),
                ],
            )
        )

        with patch(_FLAG, return_value=True):
            response = self.client.get(f"/api/projects/{self.team.id}/data_catalog/metrics/mrr/usage/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["runs"]["direct_runs"] == {"web": 3, "mcp": 5}
        assert body["runs"]["scout_runs"] == 120
        assert [(run["metric_id"], run["is_scout"]) for run in body["adjusted_runs"]] == [
            (str(mrr.id), False),
            (str(mrr.id), True),
        ]

    @parameterized.expand(
        [
            ("running_scan", timedelta(hours=1), "computing", ""),
            ("dead_scan", timedelta(hours=14), "error", SCAN_STOPPED_MESSAGE),
        ]
    )
    def test_list_reports_a_computing_row_past_the_scan_timeout_as_error(
        self, _name: str, age: timedelta, expected_status: str, expected_message: str
    ) -> None:
        row = self._snapshot(snapshot_status=UsageSnapshotStatus.COMPUTING, computed_at=None)
        UsageSnapshot.objects.for_team(self.team.id).filter(id=row.id).update(created_at=timezone.now() - age)

        with patch(_FLAG, return_value=True):
            response = self.client.get(f"/api/projects/{self.team.id}/data_catalog/usage/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [(scan["status"], scan["error_message"]) for scan in response.json()] == [
            (expected_status, expected_message)
        ]

    @parameterized.expand(
        [("denied_table", "billing", status.HTTP_404_NOT_FOUND), ("allowed_table", "events", status.HTTP_200_OK)]
    )
    @patch("products.data_catalog.backend.logic.metrics.Database.create_for")
    def test_metric_usage_404s_for_a_metric_over_a_denied_table(
        self, _name: str, table: str, expected_status: int, create_database: MagicMock
    ) -> None:
        create_database.return_value = MagicMock(_denied_tables={"billing"})
        mrr = upsert_metric(team=self.team, user=self.user, name="mrr", description="Monthly revenue")
        Metric.objects.for_team(self.team.id).filter(pk=mrr.id).update(referenced_table_names=[table])
        self._snapshot(payload=UsageSnapshotPayload(metric_runs=[_counts(mrr.id)]))

        with patch(_FLAG, return_value=True):
            response = self.client.get(f"/api/projects/{self.team.id}/data_catalog/metrics/mrr/usage/")

        assert response.status_code == expected_status, response.json()
