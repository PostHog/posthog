"""Clear suspension markers that the current counter would not produce.

A node is suspended after five consecutive failed materializations. The counter used to count
failures where the query never got to run - a busy or unreachable cluster, a preempted run - so
some nodes carry a marker they never earned. Enforcement is flag-gated, which is what makes this
worth a command rather than a wait: the markers are latent today and freeze those models all at
once when the flag widens.

Rather than judging a marker by its recorded reason, this re-runs the real counter over each one
and clears whatever it no longer reaches five on. Region-agnostic - run it once per region.

    python manage.py clear_unearned_node_suspensions              # dry-run, every team
    python manage.py clear_unearned_node_suspensions --apply
    python manage.py clear_unearned_node_suspensions --team-id 2 --apply
"""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandParser

from posthog.temporal.data_modeling.activities.utils import (
    CONSECUTIVE_FAILURES_TO_SUSPEND,
    count_leading_failures,
    is_externally_aborted,
)

from products.data_modeling.backend.logic.node_suspension import resume_nodes, suspension_reset_at, suspension_state
from products.data_modeling.backend.models.node import Node

RESUMED_BY = "suspension_recheck"


@dataclass(frozen=True, kw_only=True)
class Marker:
    node: Node
    saved_query_id: UUID
    engine: str
    reason: str
    failures: int

    @property
    def earned(self) -> bool:
        return self.failures >= CONSECUTIVE_FAILURES_TO_SUSPEND

    @property
    def blamed_on_an_abort(self) -> bool:
        return is_externally_aborted(self.reason)

    def still_unearned(self, node: Node) -> bool:
        """The sweep counts every marker before it clears any, and a model keeps failing while that
        runs, so the verdict is re-taken against the row we are about to write."""
        return (
            count_leading_failures(self.saved_query_id, self.engine, since=suspension_reset_at(node, self.engine))
            < CONSECUTIVE_FAILURES_TO_SUSPEND
        )


class Command(BaseCommand):
    help = "Clear data modeling suspension markers the current failure counter would not produce"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Limit to one team")
        parser.add_argument("--apply", action="store_true", default=False, help="Clear them (default: report only)")

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int | None = options["team_id"]
        apply: bool = options["apply"]

        markers = list(self._markers(team_id))
        unearned = [marker for marker in markers if not marker.earned]

        for marker in unearned:
            self.stdout.write(
                f"team={marker.node.team_id} node={marker.node.id} engine={marker.engine} "
                f"failures={marker.failures}/{CONSECUTIVE_FAILURES_TO_SUSPEND} "
                f"blamed_on_an_abort={'yes' if marker.blamed_on_an_abort else 'no'}"
            )

        teams = len({marker.node.team_id for marker in markers})
        blamed = sum(1 for marker in unearned if marker.blamed_on_an_abort)
        self.stdout.write(f"Checked {len(markers)} marker(s) across {teams} team(s).")
        self.stdout.write(f"  unearned: {len(unearned)} ({blamed} blamed on a run that never executed)")
        self.stdout.write(f"  earned:   {len(markers) - len(unearned)}")

        if not apply:
            self.stdout.write("Dry run. Re-run with --apply to clear the unearned ones.")
            return

        # one call per marker, because clearing every engine of a node would free markers its other
        # engines did earn
        cleared = sum(
            resume_nodes([marker.node], by=RESUMED_BY, engine=marker.engine, only_if=marker.still_unearned)
            for marker in unearned
        )
        self.stdout.write(f"Cleared {cleared} marker(s).")

    def _markers(self, team_id: int | None) -> Iterator[Marker]:
        nodes = Node.objects.filter(properties__system__has_key="suspended", saved_query__isnull=False)
        if team_id is not None:
            nodes = nodes.filter(team_id=team_id)

        for node in nodes.iterator():
            saved_query_id = node.saved_query_id
            if saved_query_id is None:
                continue  # the queryset already excludes these; this is what narrows the type
            for engine, entry in suspension_state(node).items():
                yield Marker(
                    node=node,
                    saved_query_id=saved_query_id,
                    engine=engine,
                    reason=entry.get("reason") or "",
                    failures=count_leading_failures(saved_query_id, engine, since=suspension_reset_at(node, engine)),
                )
