from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterator, NamedTuple

import structlog
from clickhouse_driver.errors import ErrorCodes, ServerException
from django.core.management.base import BaseCommand, CommandError

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.team.team import Team


logger = structlog.get_logger(__name__)


class Range(NamedTuple):
    lower: int  # lower bound, inclusive
    upper: int  # upper bound, exclusive

    @property
    def size(self):
        return self.upper - self.lower

    def split(self) -> Iterator[Range]:
        if self.size < 2:
            raise ValueError("cannot split range")

        midpoint = self.lower + (self.upper - self.lower) // 2
        return iter(
            [
                Range(self.lower, midpoint),
                Range(midpoint, self.upper),
            ]
        )


@dataclass
class BackfillQuery:
    team_id: int
    range: Range = Range(0, 2**64)

    def split(self) -> Iterator[BackfillQuery]:
        for chunk in self.range.split():
            yield BackfillQuery(self.team_id, chunk)

    def execute(self, dry_run: bool = False) -> None:
        query = """
            SELECT
                team_id,
                distinct_id,
                pdi.person_id as person_id,
                -1 as version  -- overrides that come in via Kafka will overwrite this
            FROM events
            LEFT JOIN (
                SELECT
                    distinct_id,
                    argMax(person_id, version) as person_id
                FROM person_distinct_id2
                WHERE
                    team_id = %(team_id)s
                    AND %(range_lower)s <= cityHash64(distinct_id)
                    AND cityHash64(distinct_id) < %(range_upper)s
                GROUP BY ALL
            ) pdi
                ON pdi.distinct_id = events.distinct_id
            WHERE
                team_id = %(team_id)s
                and %(range_lower)s <= cityHash64(distinct_id)
                and cityHash64(distinct_id) < %(range_upper)s
                and events.person_id != pdi.person_id
            GROUP BY ALL
        """

        parameters = {
            "team_id": self.team_id,
            "range_lower": self.range.lower,
            "range_upper": self.range.upper,
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
                    (team_id, distinct_id, person_id, version)
                    {query}
                """,
                parameters,
            )


def execute_backfill(query: BackfillQuery, dry_run: bool = False) -> None:
    logger.info(f"Executing %r...", query)
    try:
        query.execute(dry_run=dry_run)
    except ServerException as e:
        if e.code not in {ErrorCodes.TOO_SLOW, ErrorCodes.TOO_MANY_ROWS}:
            raise e
        logger.warn(f"Caught %s when running %r! Trying smaller ranges...", e, query)
        for chunk in query.split():
            execute_backfill(chunk)
    else:
        logger.info("Successfully executed %r.", query)


class Command(BaseCommand):
    help = "Backfill the person_distinct_id_overrides for a team."

    def add_arguments(self, parser):
        parser.add_argument("--team-id", required=True, type=int, help="team to backfill for")
        parser.add_argument("--live-run", action="store_true", help="execute INSERT queries (default is dry-run)")

    def handle(self, *, team_id: int, live_run: bool, **options):
        logger.setLevel(logging.INFO)

        if not Team.objects.filter(id=team_id).exists():
            raise CommandError(f"Team with id={team_id!r} does not exist")

        execute_backfill(BackfillQuery(team_id), dry_run=not live_run)
