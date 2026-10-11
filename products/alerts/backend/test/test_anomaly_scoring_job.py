from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.schema import EventsNode, FunnelsQuery, IntervalType, TrendsQuery

from posthog.models import Team
from posthog.schema_enums import AlertCalculationInterval

from products.alerts.backend.anomaly_scoring.job import (
    FAILURE_BACKOFF_BASE,
    INGESTION_LAG,
    SKIPPED_RECHECK,
    DueInsight,
    ScoreStatus,
    due_insights,
    score_and_record,
)
from products.alerts.backend.anomaly_scoring.scoring import InsightScores, ScoredPoint, ScoredSeries
from products.alerts.backend.models import InsightAnomalyConfig, InsightAnomalyState
from products.alerts.backend.models.alert import AlertConfiguration, Threshold
from products.metrics.backend.facade.contracts import GaugeWriteResult
from products.product_analytics.backend.facade.models import Insight

TRENDS = {"kind": "InsightVizNode", "source": TrendsQuery(series=[EventsNode(event="$pageview")]).model_dump()}
FUNNEL = FunnelsQuery(series=[EventsNode(event="a"), EventsNode(event="b")]).model_dump()


class TestDueInsights(BaseTest):
    def _insight(self, team_id: int | None = None, query: dict[str, Any] = TRENDS, **fields: Any) -> Insight:
        return Insight.objects.create(team_id=team_id or self.team.id, query=query, **fields)

    def _state(self, insight: Insight, **fields: Any) -> InsightAnomalyState:
        return InsightAnomalyState.objects.for_team(insight.team_id).create(
            team_id=insight.team_id, insight=insight, **fields
        )

    def test_selects_saved_trends_insights_that_are_due_or_edited(self) -> None:
        now = timezone.now()
        never_scored = self._insight()
        due = self._insight()
        self._state(due, next_due_at=now - timedelta(minutes=1), last_run_at=now - timedelta(days=1))
        edited_after_skip = self._insight(last_modified_at=now - timedelta(minutes=5))
        self._state(edited_after_skip, next_due_at=now + SKIPPED_RECHECK, last_run_at=now - timedelta(hours=1))

        not_due = self._insight(last_modified_at=now - timedelta(days=2))
        self._state(not_due, next_due_at=now + timedelta(hours=1), last_run_at=now - timedelta(days=1))
        disabled = self._insight()
        InsightAnomalyConfig.objects.for_team(self.team.id).create(
            team_id=self.team.id, insight=disabled, enabled=False
        )
        self._insight(query=FUNNEL)
        self._insight(saved=False)
        self._insight(deleted=True)
        other_team = Team.objects.create(organization=self.organization, name="Other")
        self._insight(team_id=other_team.id)

        found = due_insights(now, team_ids=[self.team.id], per_team_limit=50, total_limit=50)

        assert {d.insight_id for d in found} == {never_scored.id, due.id, edited_after_skip.id}

    def test_caps_each_team_and_ranks_insights_with_alerts_first(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        with_alert = self._insight()
        threshold = Threshold.objects.create(team=self.team, insight=with_alert, configuration={})
        AlertConfiguration.objects.create(
            team=self.team,
            insight=with_alert,
            name="alert",
            calculation_interval=AlertCalculationInterval.DAILY.value,
            config={"type": "TrendsAlertConfig", "series_index": 0},
            threshold=threshold,
        )
        self._insight()
        self._insight()
        self._insight(team_id=other_team.id)
        self._insight(team_id=other_team.id)

        found = due_insights(timezone.now(), team_ids=[], per_team_limit=1, total_limit=10)

        assert sorted(d.team_id for d in found) == sorted([self.team.id, other_team.id])
        assert DueInsight(team_id=self.team.id, insight_id=with_alert.id) in found


class TestScoreAndRecord(BaseTest):
    now = datetime(2026, 10, 10, 12, tzinfo=UTC)
    last_bucket = datetime(2026, 10, 9, tzinfo=UTC)

    def _scores(self) -> InsightScores:
        return InsightScores(
            interval=IntervalType.DAY,
            detector_type="zscore",
            detector_version="abc",
            series=[
                ScoredSeries(
                    series_index=0,
                    label="$pageview",
                    breakdown_value=None,
                    points=[ScoredPoint(bucket=self.last_bucket, value=1.0, score=0.1, flag=False)],
                )
            ],
        )

    def _state(self, insight: Insight) -> InsightAnomalyState:
        return InsightAnomalyState.objects.for_team(self.team.id).get(insight=insight)

    def test_success_advances_state_and_next_run_reads_after_the_last_bucket(self) -> None:
        insight = Insight.objects.create(team=self.team, query=TRENDS)
        with (
            patch("products.alerts.backend.anomaly_scoring.job.score_insight", return_value=self._scores()) as score,
            patch(
                "products.alerts.backend.anomaly_scoring.emit.write_gauges",
                return_value=GaugeWriteResult(written=3, dropped_stale=0),
            ),
        ):
            first = score_and_record(team_id=self.team.id, insight_id=insight.id, now=self.now)
            score_and_record(team_id=self.team.id, insight_id=insight.id, now=self.now)

        assert first.status == ScoreStatus.SCORED
        assert first.written == 3
        state = self._state(insight)
        assert state.last_scored_bucket == self.last_bucket
        # The next daily bucket starts on the 10th and closes on the 11th.
        assert state.next_due_at == datetime(2026, 10, 11, tzinfo=UTC) + INGESTION_LAG
        assert score.call_args_list[0].kwargs["after"] is None
        assert score.call_args_list[1].kwargs["after"] == self.last_bucket

    def test_failures_back_off_and_keep_the_last_scored_bucket(self) -> None:
        insight = Insight.objects.create(team=self.team, query=TRENDS)
        with (
            patch("products.alerts.backend.anomaly_scoring.job.score_insight", return_value=self._scores()),
            patch("products.alerts.backend.anomaly_scoring.emit.write_gauges", side_effect=ConnectionError("down")),
        ):
            score_and_record(team_id=self.team.id, insight_id=insight.id, now=self.now)
            outcome = score_and_record(team_id=self.team.id, insight_id=insight.id, now=self.now)

        assert outcome.status == ScoreStatus.FAILED
        state = self._state(insight)
        assert state.consecutive_failures == 2
        assert state.next_due_at == self.now + 2 * FAILURE_BACKOFF_BASE
        assert state.last_scored_bucket is None
        assert "down" in (state.last_error or "")

    @parameterized.expand(
        [
            ("funnel_insight", FUNNEL, None),
            ("ai_detector", TRENDS, {"type": "llm"}),
        ]
    )
    def test_unscorable_insights_are_skipped_until_rechecked(
        self, _name: str, query: dict[str, Any], detector_config: dict[str, Any] | None
    ) -> None:
        insight = Insight.objects.create(team=self.team, query=query)
        if detector_config:
            InsightAnomalyConfig.objects.for_team(self.team.id).create(
                team_id=self.team.id, insight=insight, detector_config=detector_config
            )

        outcome = score_and_record(team_id=self.team.id, insight_id=insight.id, now=self.now)

        assert outcome.status == ScoreStatus.SKIPPED
        state = self._state(insight)
        assert state.skip_reason
        assert state.next_due_at == self.now + SKIPPED_RECHECK
