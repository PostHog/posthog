from __future__ import annotations

import time
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from asgiref.sync import async_to_sync
from temporalio.common import RetryPolicy

from posthog.models.team import Team
from posthog.temporal.common.client import async_connect

from products.business_knowledge.backend import logic
from products.business_knowledge.backend.temporal.learning.constants import (
    LEARNING_DEFAULT_LOOKBACK_DAYS,
    LEARNING_MAX_LOOKBACK_DAYS,
)
from products.business_knowledge.backend.temporal.learning.coordinator import (
    BusinessKnowledgeLearningCoordinatorWorkflow,
)
from products.business_knowledge.backend.temporal.learning.schemas import (
    LearningCoordinatorInput,
    LearningCoordinatorOutput,
)


async def _run_learning(input: LearningCoordinatorInput) -> LearningCoordinatorOutput:
    client = await async_connect()
    return await client.execute_workflow(
        BusinessKnowledgeLearningCoordinatorWorkflow.run,
        input,
        id=f"business-knowledge-learning-manual-{input.team_id}-{time.time_ns()}",
        task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        execution_timeout=timedelta(minutes=10),
        retry_policy=RetryPolicy(maximum_attempts=1),
    )


class Command(BaseCommand):
    help = "Run a bounded Business knowledge learning pass or disable learned knowledge."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="Environment or project team ID.")
        parser.add_argument("--ticket-id", type=str, help="Analyze only this resolved ticket UUID.")
        parser.add_argument(
            "--lookback-days",
            type=int,
            default=LEARNING_DEFAULT_LOOKBACK_DAYS,
            help=f"Read resolved tickets from the last N days, up to {LEARNING_MAX_LOOKBACK_DAYS}.",
        )
        parser.add_argument(
            "--disable-generated-source",
            action="store_true",
            help="Remove learned documents from search without deleting them.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        try:
            Team.objects.only("id").get(pk=team_id)
        except Team.DoesNotExist as error:
            raise CommandError(f"Team {team_id} does not exist.") from error

        if options["disable_generated_source"]:
            changed = logic.set_generated_knowledge_source_ready(team_id, ready=False)
            message = (
                "Learned documents are no longer searchable."
                if changed
                else "This project has no generated Business knowledge source."
            )
            self.stdout.write(self.style.SUCCESS(message))
            return

        lookback_days: int = options["lookback_days"]
        if lookback_days <= 0 or lookback_days > LEARNING_MAX_LOOKBACK_DAYS:
            raise CommandError(f"--lookback-days must be between 1 and {LEARNING_MAX_LOOKBACK_DAYS}.")
        ticket_id: str | None = options["ticket_id"]
        if ticket_id is not None:
            try:
                UUID(ticket_id)
            except ValueError as error:
                raise CommandError("--ticket-id must be a UUID.") from error

        result = async_to_sync(_run_learning)(
            LearningCoordinatorInput(
                team_id=team_id,
                ticket_id=ticket_id,
                lookback_days=lookback_days,
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Found {result.eligible_count} eligible revision(s), started {result.started_count}, "
                f"skipped {result.skipped_count}."
            )
        )
