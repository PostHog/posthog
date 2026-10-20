"""Turn materialization back on for saved queries that a failure to schedule switched off.

schedule_materialization used to clear is_materialized on any error, a Temporal outage included,
and nothing turns it back on. Give this command the saved query ids from the captured
scheduling errors. It skips a query that is deleted or materialized again, and schedules the
rest. A query that fails to schedule again goes back to off, so the summary reports it.

    python manage.py reenable_materialization --ids-file ids.txt              # dry-run
    python manage.py reenable_materialization --ids-file ids.txt --apply
    python manage.py reenable_materialization --saved-query-ids <id>,<id> --apply
"""

from pathlib import Path
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery


class Command(BaseCommand):
    help = "Re-enable materialization for saved queries that a failure to schedule switched off"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--saved-query-ids", type=str, default="", help="Comma-separated saved query ids")
        parser.add_argument("--ids-file", type=Path, default=None, help="File with one saved query id per line")
        parser.add_argument("--apply", action="store_true", default=False, help="Re-enable them (default: report only)")

    def handle(self, *args: Any, **options: Any) -> None:
        ids = self._parse_ids(options["saved_query_ids"], options["ids_file"])
        apply: bool = options["apply"]

        candidates = list(
            DataWarehouseSavedQuery.objects.filter(id__in=ids, deleted=False, is_materialized=False).order_by(
                "team_id", "id"
            )
        )
        self.stdout.write(f"{len(candidates)} of {len(ids)} saved query id(s) are live and not materialized.")
        for saved_query in candidates:
            self.stdout.write(f"team={saved_query.team_id} saved_query={saved_query.id} name={saved_query.name}")

        if not apply:
            self.stdout.write("Dry run. Re-run with --apply to re-enable them.")
            return

        reenabled = 0
        failed = 0
        for saved_query in candidates:
            saved_query.is_materialized = True
            saved_query.save(update_fields=["is_materialized"])
            try:
                saved_query.schedule_materialization()
            except Exception as e:
                # A rejected frequency or another outage raises without touching the flag.
                saved_query.is_materialized = False
                saved_query.save(update_fields=["is_materialized"])
                self.stdout.write(f"failed saved_query={saved_query.id}: {e}")
                failed += 1
                continue
            saved_query.refresh_from_db(fields=["is_materialized"])
            if saved_query.is_materialized:
                reenabled += 1
            else:
                self.stdout.write(f"failed saved_query={saved_query.id}: scheduling switched it off again")
                failed += 1

        self.stdout.write(f"Re-enabled {reenabled}, failed {failed}.")

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
