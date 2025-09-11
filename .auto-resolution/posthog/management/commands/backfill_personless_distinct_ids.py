from __future__ import annotations

import time
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

import structlog

from posthog.clickhouse.client.execute import sync_execute as ch_execute
from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)


def batch_insert_personless_distinct_ids(data, batch_size=1000):
    query = """
    INSERT INTO posthog_personlessdistinctid (team_id, distinct_id, is_merged, created_at)
    VALUES %s
    ON CONFLICT (team_id, distinct_id) DO NOTHING
    """

    team_ids = {d[0] for d in data}
    existing_team_ids = set(Team.objects.filter(id__in=team_ids).values_list("id", flat=True))
    missing_team_ids = team_ids - existing_team_ids
    original_len = len(data)
    data = [d for d in data if d[0] in existing_team_ids]
    if missing_team_ids:
        logger.info(
            f"Skipping team ids {missing_team_ids!r} because they no longer exist, skipping {original_len - len(data)} records"
        )

    def chunks(lst, n):
        for i in range(0, len(lst), n):
            yield lst[i : i + n]

    for batch in chunks(data, batch_size):
        with transaction.atomic():
            with connection.cursor() as cursor:
                values = ",".join(
                    cursor.mogrify("(%s, %s, false, now())", (team_id, distinct_id)) for team_id, distinct_id in batch
                )
                full_query = query % values

                start = time.time()
                cursor.execute(full_query)
                logger.info("Inserted %r records in %r seconds", len(batch), time.time() - start)


@dataclass
class BackfillTeam:
    team_id: int

    def execute(self, dry_run: bool = False) -> None:
        logger.info("Starting %r...", self)

        query = """
        SELECT team_id, distinct_id
        FROM events
        WHERE timestamp >= '2024-04-30'
              AND timestamp < '2024-07-02'
              AND person_mode = 'propertyless'
              AND team_id = %(team_id)s
        GROUP BY team_id, distinct_id
        """

        parameters = {
            "team_id": self.team_id,
        }

        settings = {"max_execution_time": 300}

        if dry_run:
            [(count,)] = ch_execute(f"SELECT count() FROM ({query})", parameters, settings=settings)
            logger.info("%r would have inserted %r records.", self, count)
        else:
            distinct_ids = ch_execute(query, parameters, settings=settings)
            batch_insert_personless_distinct_ids(distinct_ids)
            logger.info("Completed %r (%d rows)!", self, len(distinct_ids))


@dataclass
class BackfillShard:
    shard_count: int
    shard_num: int

    def execute(self, dry_run: bool = False) -> None:
        logger.info("Starting %r...", self)

        query = """
        SELECT team_id, distinct_id
        FROM events
        WHERE timestamp >= '2024-04-30'
              AND timestamp < '2024-07-02'
              AND person_mode = 'propertyless'
              AND team_id %% %(shard_count)s = %(shard_num)s
        GROUP BY team_id, distinct_id
        """

        parameters = {
            "shard_count": self.shard_count,
            "shard_num": self.shard_num,
        }

        settings = {"max_execution_time": 300}

        if dry_run:
            [(count,)] = ch_execute(f"SELECT count() FROM ({query})", parameters, settings=settings)
            logger.info("%r would have inserted %r records.", self, count)
        else:
            distinct_ids = ch_execute(query, parameters, settings=settings)
            batch_insert_personless_distinct_ids(distinct_ids)
            logger.info("Completed %r (%d rows)!", self, len(distinct_ids))


class Command(BaseCommand):
    help = "Backfill posthog_personlessdistinctid records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            required=False,
            type=int,
            dest="team_id_list",
            action="append",
            help="team(s) to backfill",
        )
        parser.add_argument(
            "--shard-count",
            required=False,
            type=int,
            dest="shard_count",
            action="store",
            help="number of shards",
        )
        parser.add_argument(
            "--shard-num",
            required=False,
            type=int,
            dest="shard_num",
            action="store",
            help="shard number to backfill",
        )
        parser.add_argument(
            "--live-run", action="store_true", help="actually execute INSERT queries (default is dry-run)"
        )

    def handle(
        self,
        *,
        live_run: bool,
        team_id_list: Sequence[int] | None,
        shard_count: int | None,
        shard_num: int | None,
        **options,
    ):
        logger.setLevel(logging.INFO)

        if shard_count is not None and shard_num is not None:
            logger.info("Starting backfill for shard %s/%s...", shard_num, shard_count)
            BackfillShard(shard_count, shard_num).execute(dry_run=not live_run)
        elif team_id_list is not None:
            team_ids = set(team_id_list)
            existing_team_ids = set(Team.objects.filter(id__in=team_ids).values_list("id", flat=True))
            if existing_team_ids != team_ids:
                raise CommandError(f"Teams with ids {team_ids - existing_team_ids!r} do not exist")

            logger.info("Starting backfill for %s teams...", len(team_ids))
            for team_id in team_ids:
                BackfillTeam(team_id).execute(dry_run=not live_run)
        else:
            raise CommandError("Either --team-id or --shard-count and --shard-num must be specified")
