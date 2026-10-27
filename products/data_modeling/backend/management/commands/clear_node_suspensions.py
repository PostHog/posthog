"""Clear suspension markers on a chosen set of nodes.

`clear_unearned_node_suspensions` frees markers the failure counter would no longer produce. This
command is for markers the counter did earn, but for a cause on our side: a ClickHouse incident that
failed every run with the same error, or a Trino shadow compiler gap that has since been fixed.
The operator names the set; the command never decides what deserves to be cleared.

At least one of --node-ids, --saved-query-ids or --reason-contains is required, so a run cannot
clear the whole fleet by omission. Filters combine with AND. Region-agnostic - run it once per region.

    python manage.py clear_node_suspensions --engine clickhouse --reason-contains TOO_MANY_SIMULTANEOUS_QUERIES \\
        --suspended-from <iso-time> --suspended-to <iso-time>
    python manage.py clear_node_suspensions --engine managed_warehouse --team-id 2 \\
        --reason-contains TRINO_AST_EXPANSION_LIMIT --apply
    python manage.py clear_node_suspensions --saved-query-ids <uuid>,<uuid> --apply
"""

import datetime as dt
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.data_modeling.backend.logic.node_suspension import unsuspend_nodes
from products.data_modeling.backend.logic.node_suspension_selection import Selection, matching_suspension_markers

RESUMED_BY = "operator"


def _uuid_list(value: str) -> list[UUID]:
    return [UUID(item.strip()) for item in value.split(",") if item.strip()]


def _aware_datetime(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("include a UTC offset, for example 2026-09-29T00:00:00+00:00")
    return parsed


class Command(BaseCommand):
    help = "Clear data modeling suspension markers on an operator-chosen set of nodes"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Limit to one team")
        parser.add_argument("--node-ids", type=_uuid_list, default=None, help="Comma-separated node ids")
        parser.add_argument(
            "--saved-query-ids",
            type=_uuid_list,
            default=None,
            help="Comma-separated saved query ids; selects every node backing each query",
        )
        parser.add_argument("--engine", default=None, help="Only markers for this engine, e.g. clickhouse")
        parser.add_argument(
            "--reason-contains",
            action="append",
            default=[],
            help="Only markers whose recorded error contains this text. Repeat to match any of several.",
        )
        parser.add_argument("--suspended-from", type=_aware_datetime, default=None, help="ISO time, inclusive")
        parser.add_argument("--suspended-to", type=_aware_datetime, default=None, help="ISO time, exclusive")
        parser.add_argument("--by", default=RESUMED_BY, help="Recorded on the reset watermark")
        parser.add_argument("--apply", action="store_true", default=False, help="Clear them (default: report only)")

    def handle(self, *args: Any, **options: Any) -> None:
        node_ids: list[UUID] | None = options["node_ids"]
        saved_query_ids: list[UUID] | None = options["saved_query_ids"]
        # An empty fragment is a substring of every reason, so it would select every marker.
        if any(not fragment.strip() for fragment in options["reason_contains"]):
            raise CommandError("--reason-contains cannot be empty.")
        if not (node_ids or saved_query_ids or options["reason_contains"]):
            raise CommandError("Name the set: pass --node-ids, --saved-query-ids or --reason-contains.")

        selection = Selection(
            engine=options["engine"],
            reason_contains=tuple(options["reason_contains"]),
            suspended_from=options["suspended_from"],
            suspended_to=options["suspended_to"],
        )
        markers = list(
            matching_suspension_markers(
                team_id=options["team_id"], node_ids=node_ids, saved_query_ids=saved_query_ids, selection=selection
            )
        )

        for marker in markers:
            self.stdout.write(
                f"team={marker.node.team_id} node={marker.node.id} saved_query={marker.node.saved_query_id} "
                f"engine={marker.engine} at={marker.at} reason={marker.reason[:160]!r}"
            )
        teams = len({marker.node.team_id for marker in markers})
        self.stdout.write(f"Matched {len(markers)} marker(s) across {teams} team(s).")

        if not options["apply"]:
            self.stdout.write("Dry run. Re-run with --apply to clear them.")
            return

        # one call per marker, because clearing every engine of a node would free markers outside the selection
        cleared = sum(
            unsuspend_nodes([marker.node], by=options["by"], engine=marker.engine, only_if=marker.unchanged)
            for marker in markers
        )
        self.stdout.write(f"Cleared {cleared} marker(s).")
        if cleared < len(markers):
            self.stdout.write(f"  {len(markers) - cleared} re-suspended or changed since the report; left alone.")
