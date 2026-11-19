"""Write the brief for one ticket.

The staff "Write the brief" button in the support product does the same thing, and is how a
support engineer reaches this. The command is for an engineer with a shell, such as when
checking a ticket the button cannot reach.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from products.conversations.backend.models import Ticket
from products.conversations.backend.ticket_brief.writer import write_brief_for_ticket


class Command(BaseCommand):
    help = "Write the ticket brief for a single ticket."

    def add_arguments(self, parser) -> None:
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--ticket-id", type=str, help="UUID of the ticket")
        group.add_argument("--ticket-number", type=int, help="Team-scoped ticket number")
        parser.add_argument("--team-id", type=int, required=True)

    def handle(self, *args, **options) -> None:
        team_id: int = options["team_id"]
        lookup = (
            {"id": options["ticket_id"]} if options.get("ticket_id") else {"ticket_number": options["ticket_number"]}
        )
        ticket = Ticket.objects.filter(team_id=team_id, **lookup).first()
        if ticket is None:
            raise CommandError(f"No ticket for team {team_id} matching {lookup}")

        output = write_brief_for_ticket(team_id=team_id, ticket_id=str(ticket.id))
        if not output.written:
            raise CommandError(f"No brief written for #{ticket.ticket_number}: {output.reason}")
        self.stdout.write(self.style.SUCCESS(f"Wrote the brief for #{ticket.ticket_number}."))
