"""Repair a static cohort whose ClickHouse membership is behind Postgres.

Static cohort membership lives in two stores with different readers. Postgres backs the cohort
count, the membership check and flag evaluation. ClickHouse ``person_static_cohort`` backs HogQL
``IN COHORT``. A member that reached only Postgres is therefore in the cohort everywhere except
HogQL, which returns false for it with no error.

    manage.py resync_static_cohort_to_clickhouse --team-id 2 --cohort-id 433564
    manage.py resync_static_cohort_to_clickhouse --team-id 2 --cohort-id 433564 --dry-run
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

import structlog

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.util import count_cohort_members, insert_cohort_people_into_ch

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Rewrite a static cohort's ClickHouse membership from its Postgres membership."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--cohort-id", type=int, required=True)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report the Postgres member count and write nothing.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        cohort_id: int = options["cohort_id"]

        cohort = Cohort.objects.filter(id=cohort_id, team_id=team_id).first()
        if cohort is None:
            raise CommandError(f"Cohort {cohort_id} not found in team {team_id}")
        if not cohort.is_static:
            raise CommandError(f"Cohort {cohort_id} is not static; recalculate it instead")

        pg_count = count_cohort_members(team_id=team_id, cohort_id=cohort_id, consistency="strong")

        if options["dry_run"]:
            self.stdout.write(f"Cohort {cohort_id} holds {pg_count} members in Postgres. Wrote nothing.")
            return

        written = insert_cohort_people_into_ch(cohort, team_id=team_id)
        logger.info(
            "resync_static_cohort_to_clickhouse_complete",
            cohort_id=cohort_id,
            team_id=team_id,
            postgres_members=pg_count,
            written=written,
        )
        self.stdout.write(f"Wrote {written} of {pg_count} Postgres members to ClickHouse for cohort {cohort_id}.")
