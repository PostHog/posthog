from datetime import UTC, datetime, timedelta
from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.team import Team

from products.data_catalog.backend.facade.contracts import AdjustedRun, MetricRunCounts, UsageSnapshotPayload
from products.data_catalog.backend.facade.enums import FetchOutcome, JudgeRelation, UsageSnapshotStatus
from products.data_catalog.backend.logic.metrics import upsert_metric
from products.data_catalog.backend.logic.usage_snapshots import payload_to_json
from products.data_catalog.backend.models import UsageSnapshot

_FLAG = "products.data_catalog.backend.logic.usage_snapshots.posthoganalytics.feature_enabled"
_WINDOW_END = datetime(2026, 10, 26, tzinfo=UTC)


def _adjusted(metric_id: UUID, outcome: FetchOutcome, *, is_scout: bool = False) -> AdjustedRun:
    return AdjustedRun(
        metric_id=metric_id,
        fetch_outcome=outcome,
        relation=JudgeRelation.SERVES,
        intent="weekly signups",
        sql="select count() from events",
        reasoning="Same event and aggregate.",
        occurred_at=_WINDOW_END - timedelta(days=1),
        session_id=None,
        is_scout=is_scout,
    )


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
                        source_insight_dashboard_runs=0,
                        source_insight_insight_runs=0,
                    ),
                    MetricRunCounts(
                        metric_id=arr.id,
                        direct_runs={"web": 9},
                        direct_people=1,
                        scout_runs=0,
                        source_insight_dashboard_runs=0,
                        source_insight_insight_runs=0,
                    ),
                ],
                adjusted_runs=[
                    _adjusted(mrr.id, FetchOutcome.ADAPTED),
                    _adjusted(mrr.id, FetchOutcome.SILENT),
                    _adjusted(mrr.id, FetchOutcome.SILENT, is_scout=True),
                    _adjusted(arr.id, FetchOutcome.MISSED),
                ],
            )
        )

        with patch(_FLAG, return_value=True):
            response = self.client.get(f"/api/projects/{self.team.id}/data_catalog/metrics/mrr/usage/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["runs"]["direct_runs"] == {"web": 3, "mcp": 5}
        assert body["runs"]["scout_runs"] == 120
        assert body["adjusted"] == {"adapted": 1, "missed": 0, "silent": 1}
        assert body["scout_adjusted"] == {"adapted": 0, "missed": 0, "silent": 1}
        assert {run["metric_id"] for run in body["adjusted_runs"]} == {str(mrr.id)}
