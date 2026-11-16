import json
from dataclasses import asdict
from time import monotonic
from typing import cast

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from posthog.models.team import Team

from products.customer_analytics.backend.logic.membership_backfill import (
    MembershipBackfillService,
    get_membership_group_type_index,
)


class Command(BaseCommand):
    help = "Estimate membership backfill events and date windows without writes"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)

    def handle(self, *args: object, **options: object) -> None:
        team = Team.objects.filter(id=cast(int, options["team_id"])).first()
        if team is None:
            raise CommandError("Project does not exist")
        index = get_membership_group_type_index(team)
        if index is None:
            raise CommandError("Customer analytics must be active with a valid account group type")
        plan = MembershipBackfillService(deadline=monotonic() + 300).plan(team, index, timezone.now())
        self.stdout.write(json.dumps(asdict(plan), default=str))
