from collections.abc import Iterator

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import F, Q

import structlog

from posthog.dataclasses import frozen
from posthog.models import Team

from products.data_modeling.backend.logic.insight_dag_sync import delete_insight_nodes, insight_node_ids
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.product_analytics.backend.facade.api import insight_references, sync_team_insight_lineage
from products.warehouse_sources.backend.facade.api import all_queryable_table_names

logger = structlog.get_logger(__name__)

DEFAULT_CHUNK_SIZE = 500


@frozen
class TeamBackfill:
    seen: int
    failed: int
    dropped: int

    def __str__(self) -> str:
        return f"{self.seen} insight(s) seen, {self.failed} failed, {self.dropped} stale node(s) dropped"


class Command(BaseCommand):
    help = "Write lineage nodes and edges for insights that read warehouse tables or views. Safe to re-run."

    def add_arguments(self, parser: CommandParser) -> None:
        target = parser.add_mutually_exclusive_group(required=True)
        target.add_argument("--team-id", type=int, help="Backfill the project this team belongs to")
        target.add_argument("--all-teams", action="store_true", help="Backfill every project")
        parser.add_argument(
            "--chunk-size",
            type=int,
            default=DEFAULT_CHUNK_SIZE,
            help="How many insights to load from the database at a time",
        )

    def handle(self, *args, **options) -> None:
        seen = 0
        failed = 0
        dropped = 0
        failed_teams = 0
        for team in self._teams(options["team_id"]):
            try:
                result = self._backfill_team(team, options["chunk_size"])
            except Exception as error:
                # Reading the team's insights or nodes sits outside the per-insight error boundary, so a
                # failure there would otherwise end the run for every later team.
                failed_teams += 1
                logger.exception("Failed to backfill insight lineage for team", team_id=team.pk)
                self.stdout.write(f"team {team.pk}: failed ({error})")
                continue
            seen += result.seen
            failed += result.failed
            dropped += result.dropped
            if result.seen or result.dropped:
                logger.info("Backfilled insight lineage for team", team_id=team.pk, result=str(result))
                self.stdout.write(f"team {team.pk}: {result}")
        summary = f"done: {TeamBackfill(seen=seen, failed=failed, dropped=dropped)}"
        if failed_teams:
            summary = f"{summary}, {failed_teams} team(s) failed"
        self.stdout.write(summary)
        if failed or failed_teams:
            # Raised only after every team ran, so one failing team does not stop the others and a job runner
            # still sees a partial backfill as a failure.
            raise CommandError(summary)

    def _teams(self, team_id: int | None) -> Iterator[Team]:
        """Project root teams only, because an insight always belongs to its project's root team."""
        roots = Team.objects.filter(Q(parent_team_id__isnull=True) | Q(parent_team_id=F("id")))
        if team_id is not None:
            parent_id = Team.objects.filter(pk=team_id).values_list("parent_team_id", flat=True).first()
            roots = roots.filter(pk=parent_id or team_id)
        return roots.order_by("pk").iterator()

    def _backfill_team(self, team: Team, chunk_size: int) -> TeamBackfill:
        if not self._has_warehouse_objects(team.pk):
            # No view or warehouse table means no insight here can have an edge, so every insight node
            # is stale and the team's insights are not worth reading.
            return TeamBackfill(seen=0, failed=0, dropped=self._drop_insight_nodes(team.pk, keep_live=False))
        synced = sync_team_insight_lineage(team_id=team.pk, chunk_size=chunk_size)
        return TeamBackfill(
            seen=synced.seen, failed=synced.failed, dropped=self._drop_insight_nodes(team.pk, keep_live=True)
        )

    def _has_warehouse_objects(self, team_id: int) -> bool:
        if DataWarehouseSavedQuery.objects.filter(team_id=team_id).exclude(deleted=True).exists():
            return True
        return bool(all_queryable_table_names(team_id))

    def _drop_insight_nodes(self, team_id: int, *, keep_live: bool) -> int:
        """Delete the team's insight nodes, keeping the ones whose insight is live when `keep_live` is set.

        An insight deleted outside the insight API keeps its node, which nothing else removes.
        """
        insight_ids = set(insight_node_ids(team_id))
        if keep_live and insight_ids:
            insight_ids -= {reference.id for reference in insight_references(team_id=team_id, insight_ids=insight_ids)}
        if not insight_ids:
            return 0
        return delete_insight_nodes(team_id, insight_ids)
