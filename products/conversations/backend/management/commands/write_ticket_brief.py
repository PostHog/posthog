"""Write the brief for one ticket, or print it without storing it.

The reply pipeline writes a brief on every routed ticket once a team opts in. This runs the
same activity against one ticket, so the output can be read before the setting goes on.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from products.conversations.backend.models import Ticket
from products.conversations.backend.services.ticket_brief import write_brief_for_ticket


class Command(BaseCommand):
    help = "Write (or preview) the ticket brief for a single ticket."

    def add_arguments(self, parser) -> None:
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--ticket-id", type=str, help="UUID of the ticket")
        group.add_argument("--ticket-number", type=int, help="Team-scoped ticket number")
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the brief instead of storing it. Ignores the team's opt-in setting.",
        )

    def handle(self, *args, **options) -> None:
        team_id: int = options["team_id"]
        lookup = (
            {"id": options["ticket_id"]} if options.get("ticket_id") else {"ticket_number": options["ticket_number"]}
        )
        ticket = Ticket.objects.filter(team_id=team_id, **lookup).first()
        if ticket is None:
            raise CommandError(f"No ticket for team {team_id} matching {lookup}")

        if options["dry_run"]:
            self.stdout.write(json.dumps(_preview(team_id, str(ticket.id)), indent=2, ensure_ascii=False))
            return

        output = write_brief_for_ticket(team_id=team_id, ticket_id=str(ticket.id))
        if output.written:
            self.stdout.write(self.style.SUCCESS(f"Wrote the brief for #{ticket.ticket_number}."))
            return
        if output.reason == "disabled":
            raise CommandError(
                f"Briefs are off for team {team_id}. Use --dry-run to see one, or turn on "
                "`ai_ticket_brief_enabled` in the team's conversations settings."
            )
        raise CommandError(f"No brief written for #{ticket.ticket_number}: {output.reason}")


def _preview(team_id: int, ticket_id: str) -> dict:
    """Write the brief, but capture it instead of storing it.

    Lends the activity a store that captures rather than writes, so a preview cannot drift
    from what a real run would have saved.
    """
    captured: dict = {}

    def _capture(_team_id: int, _ticket_id: str, brief: dict) -> bool:
        captured.update(brief)
        return True

    import products.conversations.backend.temporal.ai_reply.activities.write_brief as module

    real_store = module._store_brief
    module._store_brief = _capture
    try:
        output = write_brief_for_ticket(team_id=team_id, ticket_id=ticket_id)
    finally:
        module._store_brief = real_store
    if not output.written:
        raise CommandError(f"No brief: {output.reason}")
    return captured
