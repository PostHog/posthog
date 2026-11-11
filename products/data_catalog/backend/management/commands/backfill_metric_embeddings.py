import time
from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandParser

import structlog

from posthog.models import Team
from posthog.models.scoping import team_scope

from ...logic.metric_embeddings import (
    can_embed,
    metrics_needing_embedding,
    refresh_metric_embedding,
    semantic_search_enabled,
)
from ...models.metric import Metric

logger = structlog.get_logger(__name__)


@dataclass(frozen=False)
class TeamResult:
    seen: int = 0
    stale: int = 0
    refreshed: int = 0
    failed: int = 0

    def add(self, other: "TeamResult") -> None:
        self.seen += other.seen
        self.stale += other.stale
        self.refreshed += other.refreshed
        self.failed += other.failed

    def __str__(self) -> str:
        return f"{self.seen} seen, {self.stale} missing or stale, {self.refreshed} refreshed, {self.failed} failed"


class Command(BaseCommand):
    help = (
        "Embed the search text of live catalog metrics that have no embedding or a stale one. "
        "Metric writes refresh their own embedding, so this covers metrics written before semantic search, "
        "and refreshes whose task never ran."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Only backfill this team")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Only count the metrics that need an embedding, without calling the embedding worker",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help="Embed every metric again, also the ones with a current embedding (after a model change)",
        )
        parser.add_argument(
            "--skip-flag-check",
            action="store_true",
            default=False,
            help="Embed for every organization that approved AI data processing, not only the teams with "
            "the semantic search flag on. Use it to prepare teams before the flag reaches them.",
        )
        parser.add_argument(
            "--sleep-ms",
            type=int,
            default=50,
            help="Pause between embedding calls, to keep the load on the embedding worker low",
        )

    def handle(self, *args, **options) -> None:
        total = TeamResult()
        skipped_teams = 0
        for team in self._teams(options["team_id"]):
            if not self._team_allowed(team, skip_flag_check=options["skip_flag_check"]):
                skipped_teams += 1
                continue
            result = self._backfill_team(
                team, dry_run=options["dry_run"], force=options["force"], sleep_seconds=options["sleep_ms"] / 1000
            )
            total.add(result)
            if result.stale:
                logger.info("Backfilled metric embeddings for team", team_id=team.pk, result=str(result))
                self.stdout.write(f"team {team.pk}: {result}")
        verb = "would embed" if options["dry_run"] else "done"
        self.stdout.write(f"{verb}: {total}, {skipped_teams} team(s) skipped by AI consent or flag")

    def _teams(self, team_id: int | None):
        # Metrics canonicalize to the project root team, so the team ids on metric rows are root ids.
        team_ids = Metric.objects.unscoped().filter(deleted=False).values("team_id").distinct()
        teams = Team.objects.filter(pk__in=team_ids).select_related("organization")
        if team_id is not None:
            teams = teams.filter(pk=team_id)
        return teams.order_by("pk").iterator()

    def _team_allowed(self, team: Team, *, skip_flag_check: bool) -> bool:
        if not can_embed(team):
            return False
        return skip_flag_check or semantic_search_enabled(team)

    def _backfill_team(self, team: Team, *, dry_run: bool, force: bool, sleep_seconds: float) -> TeamResult:
        result = TeamResult()
        with team_scope(team.pk):
            metrics = list(Metric.objects.for_team(team.pk).filter(deleted=False).select_related("team__organization"))
            result.seen = len(metrics)
            pending = metrics if force else metrics_needing_embedding(metrics)
            result.stale = len(pending)
            if dry_run:
                return result
            for metric in pending:
                try:
                    if refresh_metric_embedding(metric, force=force).refreshed:
                        result.refreshed += 1
                except Exception:
                    # One failed call must not end the run: the next run picks the metric up again.
                    result.failed += 1
                    logger.warning("Failed to embed metric", team_id=team.pk, metric_id=str(metric.id), exc_info=True)
                if sleep_seconds:
                    time.sleep(sleep_seconds)
        return result
