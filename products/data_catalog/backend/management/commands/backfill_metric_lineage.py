from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import F, Q

import structlog

from posthog.hogql.database.database import Database

from posthog.models import Team
from posthog.models.scoping import team_scope

from products.data_modeling.backend.facade.models import Node, NodeType
from products.data_modeling.backend.facade.system_tables import DATA_MODELING_ALLOWED_SYSTEM_TABLES

from ...logic.lineage import LineageSyncOutcome, sync_metric_lineage
from ...models.metric import Metric

logger = structlog.get_logger(__name__)

METRIC_CHUNK_SIZE = 200


@dataclass(frozen=False)
class TeamResult:
    seen: int = 0
    synced: int = 0
    unresolved: int = 0
    removed: int = 0
    degraded: int = 0
    stranded: int = 0

    def add(self, other: "TeamResult") -> None:
        self.seen += other.seen
        self.synced += other.synced
        self.unresolved += other.unresolved
        self.removed += other.removed
        self.degraded += other.degraded
        self.stranded += other.stranded

    def __str__(self) -> str:
        return (
            f"{self.seen} seen, {self.synced} synced, {self.unresolved} unresolved, "
            f"{self.removed} removed, {self.degraded} degraded, {self.stranded} stranded node(s) dropped"
        )


class Command(BaseCommand):
    help = "Create lineage nodes for metrics written before the catalog started syncing them"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Only backfill this team")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Only report how many metrics would be synced, without writing any node",
        )

    def handle(self, *args, **options) -> None:
        team_id = options["team_id"]
        dry_run = options["dry_run"]
        total = TeamResult()
        failed = 0
        for team in self._teams(team_id):
            try:
                result = self._backfill_team(team, dry_run)
            except Exception as error:
                # The team's schema is built once for the whole team, outside the per-metric error
                # boundary in `sync_metric_lineage`, so a team whose warehouse it cannot read would
                # otherwise end the run and leave every later team without nodes.
                failed += 1
                logger.exception("Failed to backfill metric lineage for team", team_id=team.pk)
                self.stdout.write(f"team {team.pk}: failed ({error})")
                continue
            total.add(result)
            if result.seen or result.stranded:
                logger.info("Backfilled metric lineage for team", team_id=team.pk, result=str(result), dry_run=dry_run)
                self.stdout.write(f"team {team.pk}: {result}")
        summary = f"{'would sync' if dry_run else 'done'}: {total}"
        if failed:
            summary = f"{summary}, {failed} team(s) failed"
        self.stdout.write(summary)

    def _teams(self, team_id: int | None):
        """Project root teams only.

        A metric canonicalizes to the project root, and its node is written there, so iterating a
        child environment would sync the same metrics again against the child's schema.
        """
        roots = Team.objects.filter(Q(parent_team_id__isnull=True) | Q(parent_team_id=F("id")))
        if team_id is not None:
            roots = roots.filter(pk=self._root_team_id(team_id))
        return roots.order_by("pk").iterator()

    def _root_team_id(self, team_id: int) -> int:
        """The project root of a team id, so `--team-id` given a child environment backfills its project."""
        parent_id = Team.objects.filter(pk=team_id).values_list("parent_team_id", flat=True).first()
        return parent_id or team_id

    def _backfill_team(self, team: Team, dry_run: bool) -> TeamResult:
        result = TeamResult()
        with team_scope(team.pk):
            metrics = Metric.objects.for_team(team.pk).filter(deleted=False)
            if dry_run:
                result.seen = metrics.count()
                result.stranded = self._stranded_nodes(team).count()
                return result
            if metrics.exists():
                # One schema for the whole team: building it per metric is the expensive part.
                database = Database.create_for(
                    team=team,
                    bypass_warehouse_access_control=True,
                    allowed_system_tables=DATA_MODELING_ALLOWED_SYSTEM_TABLES,
                )
                for metric in metrics.select_related("team").iterator(chunk_size=METRIC_CHUNK_SIZE):
                    result.seen += 1
                    outcome = sync_metric_lineage(metric, database=database)
                    if outcome == LineageSyncOutcome.SYNCED:
                        result.synced += 1
                    elif outcome == LineageSyncOutcome.UNRESOLVED:
                        result.unresolved += 1
                    elif outcome == LineageSyncOutcome.REMOVED:
                        result.removed += 1
                    else:
                        result.degraded += 1
            stranded_nodes = self._stranded_nodes(team)
            result.stranded = stranded_nodes.count()
            stranded_nodes.delete()
        return result

    def _stranded_nodes(self, team: Team):
        """Metric nodes whose metric is deleted or gone.

        A metric delete removes its node best effort, so a failure there leaves the node in the
        graph with nothing to take it out again. This is that repair.
        """
        live_metric_ids = Metric.objects.for_team(team.pk).filter(deleted=False).values("id")
        return Node.objects.filter(team=team, type=NodeType.METRIC).exclude(metric_id__in=live_metric_ids)
