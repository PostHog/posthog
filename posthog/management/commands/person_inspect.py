"""Show the Postgres and ClickHouse state of explicit persons and distinct ids, and their flavor.

Usage:
    python manage.py person_inspect --team-id 2 --person-uuid <uuid> --distinct-id <id>

Read-only. Prints one JSON object per key. Distinct ids are hashed unless --show-distinct-ids is passed.
"""

import json
import dataclasses
from datetime import UTC, datetime
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.person.divergence.inspection import hash_distinct_id, inspect_mappings, inspect_persons


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


class Command(BaseCommand):
    help = "Read-only. Show the Postgres and ClickHouse state and the flavor of explicit persons and distinct ids."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--person-uuid", action="append", default=[], help="Person to inspect. Repeatable.")
        parser.add_argument("--distinct-id", action="append", default=[], help="Distinct id to inspect. Repeatable.")
        parser.add_argument(
            "--purged-at",
            type=_parse_utc,
            default=None,
            help="When the team's Postgres persons were purged; dates a ghost as after_purge or historical.",
        )
        parser.add_argument(
            "--show-distinct-ids", action="store_true", help="Print distinct ids as they are instead of hashed."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not options["person_uuid"] and not options["distinct_id"]:
            raise CommandError("Pass at least one --person-uuid or --distinct-id")
        team_id = options["team_id"]
        with tags_context(product=Product.INTERNAL, feature=Feature.MANAGEMENT_COMMAND):
            inspections = [
                *inspect_persons(team_id, options["person_uuid"], purged_at=options["purged_at"]),
                *inspect_mappings(team_id, options["distinct_id"]),
            ]
        for inspection in inspections:
            row = dataclasses.asdict(inspection)
            if inspection.kind == "mapping" and not options["show_distinct_ids"]:
                row["key"] = hash_distinct_id(team_id, inspection.key)
            self.stdout.write(json.dumps(row, sort_keys=True))
