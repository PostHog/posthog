"""Score a trends insight's series with its anomaly detector and print the result.

Writes nothing yet: only --dry-run is supported until scores can be stored in Metrics.

    python manage.py score_insight_anomalies --insight 123 --dry-run
    python manage.py score_insight_anomalies --insight 123 --dry-run --all-points
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from products.alerts.backend.anomaly_scoring.config import effective_config
from products.alerts.backend.anomaly_scoring.scoring import (
    InsightScores,
    ScoredPoint,
    UnsupportedInsightError,
    score_insight,
)
from products.alerts.backend.models import InsightAnomalyConfig, InsightAnomalyState
from products.product_analytics.backend.facade.models import Insight


class Command(BaseCommand):
    help = "Score a trends insight's series for anomalies and print value, score and flag per bucket"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--insight", type=int, required=True, help="Insight id")
        parser.add_argument("--dry-run", action="store_true", default=False, help="Print the scores, write nothing")
        parser.add_argument(
            "--all-points", action="store_true", default=False, help="Print every bucket, not only flagged ones"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not options["dry_run"]:
            raise CommandError("Only --dry-run is supported for now")

        try:
            insight = Insight.objects.select_related("team", "created_by").get(pk=options["insight"], deleted=False)
        except Insight.DoesNotExist:
            raise CommandError(f"Insight {options['insight']} not found")

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
