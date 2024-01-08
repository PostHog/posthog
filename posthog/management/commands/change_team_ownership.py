import logging
import uuid

import structlog
from django.core.management import CommandError
from django.core.management.base import BaseCommand

from posthog.models import Organization, Team

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = "Move a team into another organization."

    def add_arguments(self, parser):
        parser.add_argument("--team-id", default=None, type=int, help="Specify a team to fix data for.")
        parser.add_argument(
            "--organization-id", default=None, type=uuid.UUID, help="Specify the destination organization by UUID."
        )
        parser.add_argument("--live-run", action="store_true", help="Run changes, default is dry-run")

    def handle(self, *args, **options):
        run(options)


def run(options):
    live_run = options["live_run"]

    if options["team_id"] is None:
        raise CommandError("You must specify --team-id to run this script")

    if options["organization_id"] is None:
        raise CommandError("You must specify --organization-id to run this script")

    team_id = options["team_id"]
    organization_id = options["organization_id"]

    team = Team.objects.get(pk=team_id)
    logger.info(f"Team {team_id} is currently in organization {team.organization_id}, named {team.organization.name}")

    org = Organization.objects.get(pk=organization_id)
    logger.info(f"Target organization {organization_id} is named {org.name}")

    if team.organization_id == organization_id:
        raise CommandError("Team is already in the specified organization")

    if live_run:
        team.organization_id = organization_id
        team.save()
        logger.info("Saved team change")
    else:
        logger.info("Skipping the team change, pass --live-run to run it")
