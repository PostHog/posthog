"""Score a trends insight's series with its anomaly detector, then print the scores or write them to Metrics.

python manage.py score_insight_anomalies --insight 123 --dry-run
python manage.py score_insight_anomalies --insight 123 --dry-run --all-points
python manage.py score_insight_anomalies --insight 123 --emit
python manage.py score_insight_anomalies --via-temporal
python manage.py score_insight_anomalies --via-temporal --team 1
"""

import time
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from asgiref.sync import async_to_sync
from temporalio.common import RetryPolicy

from posthog.temporal.common.client import async_connect

from products.alerts.backend.anomaly_scoring.config import effective_config
from products.alerts.backend.anomaly_scoring.job import ScoreStatus, score_and_record
from products.alerts.backend.anomaly_scoring.scoring import (
    InsightScores,
    ScoredPoint,
    UnsupportedInsightError,
    score_insight,
)
from products.alerts.backend.models import InsightAnomalyConfig, InsightAnomalyState
from products.alerts.backend.temporal.anomaly_scoring import (
    InsightAnomalyScoringInput,
    InsightAnomalyScoringResult,
    InsightAnomalyScoringWorkflow,
)
from products.product_analytics.backend.facade.models import Insight


async def _run_tick(inputs: InsightAnomalyScoringInput) -> InsightAnomalyScoringResult:
    client = await async_connect()
    return await client.execute_workflow(
        InsightAnomalyScoringWorkflow.run,
        inputs,
        id=f"insight-anomaly-scoring-manual-{time.time_ns()}",
        task_queue=settings.SELF_DRIVING_TASK_QUEUE,
        execution_timeout=timedelta(minutes=30),
        retry_policy=RetryPolicy(maximum_attempts=1),
    )


class Command(BaseCommand):
    help = "Score a trends insight's series for anomalies, then print the scores or write them to Metrics"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--insight", type=int, help="Insight id, for --dry-run and --emit")
        parser.add_argument("--team", type=int, help="Team id, for --via-temporal. Defaults to the configured teams")
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--dry-run", action="store_true", default=False, help="Print the scores, write nothing")
        mode.add_argument(
            "--emit",
            action="store_true",
            default=False,
            help="Write the scores to the team's Metrics and advance the insight's last scored bucket",
        )
        mode.add_argument(
            "--via-temporal",
            action="store_true",
            default=False,
            help="Run one scheduled tick on the self-driving worker: score every due insight",
        )
        parser.add_argument(
            "--all-points", action="store_true", default=False, help="Print every bucket, not only flagged ones"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["via_temporal"]:
            result = async_to_sync(_run_tick)(InsightAnomalyScoringInput(team_id=options["team"]))
            self.stdout.write(str(result))
            return
        if options["insight"] is None:
            raise CommandError("--dry-run and --emit need --insight")

        try:
            insight = Insight.objects.select_related("team", "created_by").get(pk=options["insight"], deleted=False)
        except Insight.DoesNotExist:
            raise CommandError(f"Insight {options['insight']} not found")

        if options["emit"]:
            outcome = score_and_record(team_id=insight.team_id, insight_id=insight.pk, now=timezone.now())
            if outcome.status != ScoreStatus.SCORED:
                raise CommandError(f"Not scored ({outcome.status.value}): {outcome.reason or ''}")
            newest = outcome.last_scored_bucket
            self.stdout.write(
                f"Wrote {outcome.written} points; dropped {outcome.dropped_stale} too old for Metrics to keep. "
                f"Last scored bucket: {newest.isoformat() if newest else 'none yet'}"
            )
            return

        team_id = insight.team_id
        override = InsightAnomalyConfig.objects.for_team(team_id).filter(insight=insight).first()
        state = InsightAnomalyState.objects.for_team(team_id).filter(insight=insight).first()
        config = effective_config(override)
        if not config.enabled:
            self.stdout.write("Anomaly scoring is turned off for this insight.")
            return

        try:
            scores = score_insight(
                insight,
                insight.team,
                config,
                now=timezone.now(),
                after=state.last_scored_bucket if state else None,
            )
        except UnsupportedInsightError as err:
            raise CommandError(f"Not scored: {err}")
        self._print(scores, all_points=options["all_points"])

    def _print(self, scores: InsightScores, *, all_points: bool) -> None:
        self.stdout.write(
            f"interval={scores.interval.value} detector={scores.detector_type} version={scores.detector_version}"
        )
        for series in scores.series:
            flagged = [point for point in series.points if point.flag]
            name = series.label if series.breakdown_value is None else f"{series.label} [{series.breakdown_value}]"
            self.stdout.write(
                f"\nseries {series.series_index} {name}: {len(series.points)} buckets, {len(flagged)} flagged"
            )
            for point in series.points if all_points else flagged:
                self.stdout.write(_format_point(point))


def _format_point(point: ScoredPoint) -> str:
    score = "-" if point.score is None else f"{point.score:.3f}"
    return f"  {point.bucket.isoformat()}  value={point.value:g}  score={score}  flag={int(point.flag)}"
