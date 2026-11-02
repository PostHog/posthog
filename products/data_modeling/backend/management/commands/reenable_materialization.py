"""Turn materialization back on for saved queries that a failure to schedule switched off.

schedule_materialization used to clear is_materialized on any error, a Temporal outage included,
and nothing turns it back on. Give this command the saved query ids from the captured
scheduling errors. It skips a query that is deleted or whose DAG node materializes again, and
schedules the rest. A query that fails to schedule again goes back to off, so the summary
reports it. The flag and the node go back on only after every Temporal call succeeds. A run that
stops in the middle, by SIGKILL too, leaves the query in progress off, so the next run tries it
again.

    python manage.py reenable_materialization --ids-file ids.txt              # dry-run
    python manage.py reenable_materialization --ids-file ids.txt --apply
    python manage.py reenable_materialization --saved-query-ids <id>,<id> --apply
"""

from pathlib import Path
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.db.models import Exists, OuterRef

from products.data_modeling.backend.logic.saved_query_dag_sync import promote_view_nodes_to_matview
from products.data_modeling.backend.logic.schedule_reconcile import reconcile_dag_schedules
from products.data_modeling.backend.logic.tier_run_report import MATERIALIZING_TYPES
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import Node


class SwitchedOffAgainError(Exception):
    pass


class Command(BaseCommand):
    help = "Re-enable materialization for saved queries that a failure to schedule switched off"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--saved-query-ids", type=str, default="", help="Comma-separated saved query ids")
        parser.add_argument("--ids-file", type=Path, default=None, help="File with one saved query id per line")
        parser.add_argument("--apply", action="store_true", default=False, help="Re-enable them (default: report only)")

    def handle(self, *args: Any, **options: Any) -> None:
        ids = self._parse_ids(options["saved_query_ids"], options["ids_file"])
        apply: bool = options["apply"]

        materializing_node = Node.objects.filter(saved_query_id=OuterRef("pk"), type__in=MATERIALIZING_TYPES)
        candidates = list(
            DataWarehouseSavedQuery.objects.filter(id__in=ids)
            .exclude(deleted=True)
            .exclude(Exists(materializing_node))
            .order_by("team_id", "id")
        )
        self.stdout.write(f"{len(candidates)} of {len(ids)} saved query id(s) are live and have no materializing node.")
        for saved_query in candidates:
            self.stdout.write(f"team={saved_query.team_id} saved_query={saved_query.id} name={saved_query.name}")

        if not apply:
            self.stdout.write("Dry run. Re-run with --apply to re-enable them.")
            return

        reenabled = 0
        failed = 0
        for saved_query in candidates:
            try:
                self._reenable(saved_query)
            except Exception as e:
                saved_query.is_materialized = False
                saved_query.save(update_fields=["is_materialized"])
                self.stdout.write(f"failed saved_query={saved_query.id}: {e}")
                failed += 1
            else:
                reenabled += 1

        self.stdout.write(f"Re-enabled {reenabled}, failed {failed}.")

    def _reenable(self, saved_query: DataWarehouseSavedQuery) -> None:
        # The flag reaches the database only after every Temporal call. A run that stops before then
        # leaves the query off for the next run, and no row lock waits on Temporal. Until then the flag
        # is on in memory only, where the failure paths of schedule_materialization switch it off.
        saved_query.is_materialized = True
        # The default reconcile logs a failure and does not raise it, so a query that no tier runs
        # counts as re-enabled. Reconcile below instead, where a failure raises.
        saved_query.schedule_materialization(reconcile=False)
        if not saved_query.is_materialized:
            raise SwitchedOffAgainError("scheduling switched it off again")
        nodes = Node.objects.filter(team_id=saved_query.team_id, saved_query=saved_query).select_related(
            "dag", "dag__team"
        )
        for dag in {node.dag for node in nodes}:
            reconcile_dag_schedules(dag)
        with transaction.atomic():
            saved_query.save(update_fields=["is_materialized"])
            # A failed first enable leaves the node a VIEW, and a DAG run skips a VIEW node as ephemeral.
            # The promotion reads the flag from the database, so it follows the save.
            promote_view_nodes_to_matview(saved_query)

    def _parse_ids(self, raw: str, ids_file: Path | None) -> set[UUID]:
        tokens = [token.strip() for token in raw.split(",")]
        if ids_file is not None:
            tokens.extend(line.strip() for line in ids_file.read_text().splitlines())
        try:
            ids = {UUID(token) for token in tokens if token}
        except ValueError as e:
            raise CommandError(f"Invalid saved query id: {e}")
        if not ids:
            raise CommandError("Pass --saved-query-ids or --ids-file")
        return ids
