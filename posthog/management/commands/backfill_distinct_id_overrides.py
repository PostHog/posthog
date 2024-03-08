from __future__ import annotations

import logging
from dataclasses import dataclass

import structlog
from django.core.management.base import BaseCommand, CommandError

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.team.team import Team


logger = structlog.get_logger(__name__)


@dataclass
class BackfillQuery:
    team_id: int

    def execute(self, dry_run: bool = False) -> None:
        query = """
            SELECT
                team_id,
                distinct_id,
                argMax(person_id, version),
                argMax(is_deleted, version),
                max(version)
            FROM person_distinct_id2
            WHERE
                team_id = %(team_id)s
                AND version > 0
            GROUP BY team_id, distinct_id
        """

        parameters = {
            "team_id": self.team_id,
        }

        if dry_run:
            [(count,)] = sync_execute(f"SELECT count() FROM ({query})", parameters)
            logger.info("%r would have inserted %r records.", self, count)
        else:
            # XXX: Nothing useful to report here, unfortunately... all that is
            # returned is an empty result set.
            sync_execute(
                f"""
                    INSERT INTO person_distinct_id_overrides
                    (team_id, distinct_id, person_id, is_deleted, version)
                    {query}
                """,
                parameters,
            )


class Command(BaseCommand):
    help = "Backfill person_distinct_id_overrides records."

    def add_arguments(self, parser):
        parser.add_argument("--team-id", required=True, type=int, help="team to backfill for")
        parser.add_argument(
            "--live-run", action="store_true", help="actually execute INSERT queries (default is dry-run)"
        )

    def handle(self, *, live_run: bool, team_id: int, **options):
        logger.setLevel(logging.INFO)

        if not Team.objects.filter(id=team_id).exists():
            raise CommandError(f"Team with id={team_id!r} does not exist")

        BackfillQuery(team_id).execute(dry_run=not live_run)
