"""Run the grounded support reply pipeline against a single ticket end-to-end.

Used for dogfooding the Temporal pipeline before the coordinator auto-trigger is wired up.
"""

from __future__ import annotations

import asyncio

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.temporal.common.client import async_connect

from products.conversations.backend.models import Ticket
from products.conversations.backend.temporal.pipeline import SupportReplyInput, SupportReplyWorkflow


class Command(BaseCommand):
    help = "Run the grounded support reply pipeline for a single ticket."

    def add_arguments(self, parser) -> None:
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--ticket-id", type=str, help="UUID of the ticket to process")
        group.add_argument("--ticket-number", type=int, help="Team-scoped ticket number")
        parser.add_argument("--team-id", type=int, required=True)

    def handle(self, *args, **options) -> None:
        team_id: int = options["team_id"]

        if options["ticket_id"]:
            ticket = Ticket.objects.filter(id=options["ticket_id"], team_id=team_id).first()
        else:
            ticket = Ticket.objects.filter(ticket_number=options["ticket_number"], team_id=team_id).first()

        if not ticket:
            raise CommandError(f"Ticket not found for team {team_id}")

        ticket_id = str(ticket.id)

        result = asyncio.run(self._run_workflow(team_id, ticket_id))
        self.stdout.write(self.style.SUCCESS(f"Pipeline result: {result}"))

    async def _run_workflow(self, team_id: int, ticket_id: str) -> str:
        client = await async_connect()
        workflow_id = f"support-reply-manual-{ticket_id}"
        result = await client.execute_workflow(
            SupportReplyWorkflow.run,
            SupportReplyInput(team_id=team_id, ticket_id=ticket_id),
            id=workflow_id,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        )
        return result
