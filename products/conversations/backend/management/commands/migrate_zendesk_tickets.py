"""Start a Zendesk historical import for a team (internal/ops)."""

from __future__ import annotations

import asyncio

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

import structlog

from posthog.models import Team

from products.conversations.backend.api.zendesk_import import WORKFLOW_START_FAILED_MESSAGE
from products.conversations.backend.models import ZendeskImportJob
from products.conversations.backend.temporal.zendesk_import.client import (
    ZendeskCredentials,
    validate_zendesk_credentials,
)
from products.conversations.backend.temporal.zendesk_import.starter import start_zendesk_import_workflow

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Import historical Zendesk tickets into Conversations for a team."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--subdomain", type=str, required=True)
        parser.add_argument("--email", type=str, required=True)
        parser.add_argument("--api-token", type=str, required=True)
        parser.add_argument("--dry-run", action="store_true", default=False)
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Cap total tickets imported (for testing, e.g. 10/100/1000). Omit for a full import.",
        )
        parser.add_argument(
            "--default-email-channel-id",
            type=str,
            default=None,
            help="Fallback EmailChannel id for tickets whose Zendesk recipient doesn't match a "
            "configured support address. Omit to leave those tickets without an email channel.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help="Mark any existing pending/running job for this team as failed before starting. "
            "Use to recover after a workflow was terminated out-of-band (e.g. killed in the "
            "Temporal UI), which leaves the DB row stuck 'running'.",
        )

    def handle(self, *args, **options) -> None:
        team_id: int = options["team_id"]
        team = Team.objects.filter(id=team_id).first()
        if team is None:
            raise CommandError(f"Team {team_id} not found")
        if not team.conversations_enabled:
            raise CommandError(f"Conversations is not enabled for team {team_id}")

        credentials = ZendeskCredentials(
            subdomain=options["subdomain"],
            email_address=options["email"],
            api_token=options["api_token"],
        )
        if not validate_zendesk_credentials(credentials):
            raise CommandError("Zendesk rejected the credentials")

        active_jobs = ZendeskImportJob.objects.unscoped().filter(
            team_id=team_id,
            status__in=[ZendeskImportJob.Status.PENDING, ZendeskImportJob.Status.RUNNING],
        )
        if active_jobs.exists():
            if not options["force"]:
                raise CommandError(
                    "A Zendesk import is already running for this team. "
                    "If it was terminated out-of-band (e.g. in the Temporal UI), re-run with --force."
                )
            reset = active_jobs.update(
                status=ZendeskImportJob.Status.FAILED,
                latest_error="Superseded by a --force re-import (previous job was no longer running).",
                finished_at=timezone.now(),
                updated_at=timezone.now(),
            )
            self.stdout.write(self.style.WARNING(f"--force: marked {reset} stale job(s) as failed"))

        job = ZendeskImportJob.objects.unscoped().create(
            team_id=team_id,
            status=ZendeskImportJob.Status.PENDING,
            job_inputs={
                "subdomain": credentials.subdomain,
                "email_address": credentials.email_address,
                "api_token": credentials.api_token,
            },
        )

        try:
            workflow_id, workflow_run_id = asyncio.run(
                start_zendesk_import_workflow(
                    job_id=str(job.id),
                    team_id=team_id,
                    dry_run=options["dry_run"],
                    max_tickets=options["limit"],
                    default_email_channel_id=options["default_email_channel_id"],
                )
            )
            job.workflow_id = workflow_id
            job.workflow_run_id = workflow_run_id
            job.status = ZendeskImportJob.Status.RUNNING
            job.started_at = timezone.now()
            job.save(update_fields=["workflow_id", "workflow_run_id", "status", "started_at", "updated_at"])
        except Exception as exc:
            logger.exception("zendesk_import_workflow_start_failed", job_id=str(job.id), team_id=team_id)
            job.status = ZendeskImportJob.Status.FAILED
            job.latest_error = WORKFLOW_START_FAILED_MESSAGE
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "latest_error", "finished_at", "updated_at"])
            raise CommandError(f"Failed to start workflow: {exc}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Started Zendesk import job {job.id} (workflow {workflow_id}, "
                f"dry_run={options['dry_run']}, limit={options['limit']})"
            )
        )
