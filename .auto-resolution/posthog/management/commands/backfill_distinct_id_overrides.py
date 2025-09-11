from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError

import structlog

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)


@dataclass
class Backfill:
    team_id: int

    def execute(self, dry_run: bool = False) -> None:
        logger.info("Starting %r...", self)

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

            # XXX: The RETURNING set isn't really useful here, but this QuerySet
            # needs to be iterated over to force execution, so we might as well
            # return something...
            updated_teams = list(
                Team.objects.raw(
                    """
                    UPDATE posthog_team
                    SET extra_settings = COALESCE(extra_settings, '{}'::jsonb) || '{"distinct_id_overrides_backfilled": true}'::jsonb
                    WHERE id = %s
                    RETURNING *
                    """,
                    [self.team_id],
                )
            )
            assert not len(updated_teams) > 1

            logger.info("Completed %r!", self)


class Command(BaseCommand):
    help = "Backfill person_distinct_id_overrides records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            required=False,
            type=int,
            dest="team_id_list",
            action="append",
            help="team(s) to backfill (defaults to all un-backfilled teams)",
        )
        parser.add_argument(
            "--live-run", action="store_true", help="actually execute INSERT queries (default is dry-run)"
        )

    def handle(self, *, live_run: bool, team_id_list: Sequence[int] | None, **options):
        logger.setLevel(logging.INFO)

        if team_id_list is not None:
            team_ids = set(team_id_list)
            existing_team_ids = set(Team.objects.filter(id__in=team_ids).values_list("id", flat=True))
            if existing_team_ids != team_ids:
                raise CommandError(f"Teams with ids {team_ids - existing_team_ids!r} do not exist")
        else:
            team_ids = set(
                Team.objects.exclude(extra_settings__distinct_id_overrides_backfilled=True).values_list("id", flat=True)
            )

        logger.info("Starting backfill for %s teams...", len(team_ids))
        for team_id in team_ids:
            Backfill(team_id).execute(dry_run=not live_run)
