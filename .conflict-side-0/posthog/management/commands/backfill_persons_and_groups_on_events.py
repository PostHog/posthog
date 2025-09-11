# ruff: noqa: T201 allow print statements

import logging
from time import sleep
from typing import Any
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import reset_query_tags, tag_queries
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.group.sql import GROUPS_TABLE
from posthog.models.person.sql import PERSON_DISTINCT_ID2_TABLE, PERSONS_TABLE
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE
from posthog.settings.data_stores import CLICKHOUSE_PASSWORD

"""
WARNING: This script is in Alpha! Make sure you know what you're doing before running it with --live-run set.

Pre-requisites:

- `allow_nondeterministic_mutations` should be set to 1 on the current user's profile

Approach:

1. Create dictionaries for groups, persons, and person distinct ID tables

These dictionaries will source data from the target Replicated tables, so they are guaranteed to be consistent across nodes.
We keep a small cache in memory of 1000 frequently accessed keys for each dictionary. We hit the source table for values not in the cache.

2. Alter table to update values according to the dictionaries

With the dictionaries in place, we run an ALTER TABLE backfill. Note that this will have to rewrite a lot of data.
This backfill will look up values in the dictionaries and set the corresponding columns to them.
Also note that minor inconsitencies can occur from distinct IDs and properties changing during the backfill.

3. Drop the dictionaries
"""


logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)

backfill_query_id = str(uuid4())


GROUPS_DICT_TABLE_NAME = f"{GROUPS_TABLE}_dict"
PERSONS_DICT_TABLE_NAME = f"{PERSONS_TABLE}_dict"
PERSON_DISTINCT_IDS_DICT_TABLE_NAME = f"{PERSON_DISTINCT_ID2_TABLE}_dict"

ACCESS_CONFIG = f"DB '{CLICKHOUSE_DATABASE}' USER 'default' PASSWORD '{CLICKHOUSE_PASSWORD}'"

GROUPS_DICTIONARY_SQL = f"""
CREATE DICTIONARY IF NOT EXISTS {GROUPS_DICT_TABLE_NAME}
ON CLUSTER '{CLICKHOUSE_CLUSTER}'
(
    group_key String,
    group_properties String
)
PRIMARY KEY group_key
SOURCE(CLICKHOUSE(TABLE {GROUPS_TABLE} {ACCESS_CONFIG}))
LAYOUT(complex_key_cache(size_in_cells 10000))
Lifetime(60000)
"""


PERSON_DISTINCT_IDS_DICTIONARY_SQL = f"""
CREATE DICTIONARY IF NOT EXISTS {PERSON_DISTINCT_IDS_DICT_TABLE_NAME}
ON CLUSTER '{CLICKHOUSE_CLUSTER}'
(
    distinct_id String,
    person_id UUID
)
PRIMARY KEY distinct_id
SOURCE(CLICKHOUSE(TABLE {PERSON_DISTINCT_ID2_TABLE} {ACCESS_CONFIG}))
LAYOUT(complex_key_direct())
"""

PERSONS_DICTIONARY_SQL = f"""
CREATE DICTIONARY IF NOT EXISTS {PERSONS_DICT_TABLE_NAME}
ON CLUSTER '{CLICKHOUSE_CLUSTER}'
(
    id UUID,
    properties String
)
PRIMARY KEY id
SOURCE(CLICKHOUSE(TABLE {PERSONS_TABLE} {ACCESS_CONFIG}))
LAYOUT(complex_key_direct())
"""

backfill_settings = "SETTINGS mutations_sync = 2" if settings.TEST else ""

BACKFILL_SQL = f"""
ALTER TABLE {EVENTS_DATA_TABLE()}
ON CLUSTER '{CLICKHOUSE_CLUSTER}'
UPDATE
    person_id=toUUID(dictGet('{CLICKHOUSE_DATABASE}.{PERSON_DISTINCT_IDS_DICT_TABLE_NAME}', 'person_id', tuple(distinct_id))),
    person_properties=dictGetString('{CLICKHOUSE_DATABASE}.{PERSONS_DICT_TABLE_NAME}', 'properties', tuple(toUUID(dictGet('{CLICKHOUSE_DATABASE}.{PERSON_DISTINCT_IDS_DICT_TABLE_NAME}', 'person_id', tuple(distinct_id))))),
    group0_properties=dictGetString('{CLICKHOUSE_DATABASE}.{GROUPS_DICT_TABLE_NAME}', 'group_properties', tuple($group_0)),
    group1_properties=dictGetString('{CLICKHOUSE_DATABASE}.{GROUPS_DICT_TABLE_NAME}', 'group_properties', tuple($group_1)),
    group2_properties=dictGetString('{CLICKHOUSE_DATABASE}.{GROUPS_DICT_TABLE_NAME}', 'group_properties', tuple($group_2)),
    group3_properties=dictGetString('{CLICKHOUSE_DATABASE}.{GROUPS_DICT_TABLE_NAME}', 'group_properties', tuple($group_3)),
    group4_properties=dictGetString('{CLICKHOUSE_DATABASE}.{GROUPS_DICT_TABLE_NAME}', 'group_properties', tuple($group_4))
WHERE team_id = %(team_id)s
{backfill_settings}
"""

GET_QUERY_ID_SQL = f"""
SELECT query_id
FROM system.query_log
WHERE
    query_start_time > (now() - INTERVAL 10 MINUTE) AND
    query LIKE '%backfill:{backfill_query_id}%' AND
    query NOT LIKE '%query_log%'
LIMIT 1
"""


query_number = 0


def print_and_execute_query(sql: str, name: str, dry_run: bool, timeout=180, query_args=None) -> Any:
    if query_args is None:
        query_args = {}
    global query_number

    if not settings.TEST:
        print(f"> {query_number}. {name}", end="\n\n")
        print(sql, end="\n")
        print("---------------------------------", end="\n\n")

    query_number = query_number + 1

    if not dry_run:
        res = sync_execute(sql, settings={"max_execution_time": timeout}, args=query_args)
        return res

    return None


def run_backfill(options):
    if not options["team_id"]:
        logger.error("You must specify --team-id to run this script")
        exit(1)

    dry_run = not options["live_run"]

    if dry_run:
        print("Dry run. Queries to run:", end="\n\n")

    print_and_execute_query(GROUPS_DICTIONARY_SQL, "GROUPS_DICTIONARY_SQL", dry_run)
    print_and_execute_query(
        PERSON_DISTINCT_IDS_DICTIONARY_SQL,
        "PERSON_DISTINCT_IDS_DICTIONARY_SQL",
        dry_run,
    )
    print_and_execute_query(PERSONS_DICTIONARY_SQL, "PERSONS_DICTIONARY_SQL", dry_run)

    tag_queries(kind="backfill", id=backfill_query_id)
    print_and_execute_query(
        BACKFILL_SQL,
        "BACKFILL_SQL",
        dry_run,
        0,
        {"team_id": options["team_id"], "id": backfill_query_id},
    )
    reset_query_tags()

    if dry_run or settings.TEST:
        return

    # it can take a little while for the query to show up on the query_log
    sleep(10)
    query_id_res = print_and_execute_query(GET_QUERY_ID_SQL, "GET_QUERY_ID_SQL", dry_run)

    if query_id_res:
        query_id = query_id_res[0][0]
        print()
        print(
            f"Backfill running. Cancel backfill by running:\n`KILL QUERY ON CLUSTER {CLICKHOUSE_CLUSTER} WHERE query_id='{query_id}'`"
        )


class Command(BaseCommand):
    help = "Backfill persons and groups data on events for a given team"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            default=None,
            type=str,
            help="Specify a team to backfill data for.",
        )

        parser.add_argument(
            "--live-run",
            action="store_true",
            help="Opts out of default 'dry run' mode and actually runs the queries.",
        )

    def handle(self, *args, **options):
        run_backfill(options)
