import structlog
from django.core.management.base import BaseCommand

from ee.clickhouse.sql.events import EVENTS_DATA_TABLE
from ee.clickhouse.sql.groups import GROUPS_TABLE
from ee.clickhouse.sql.person import PERSON_DISTINCT_ID2_TABLE, PERSONS_TABLE
from posthog.client import sync_execute
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE
from posthog.settings.data_stores import CLICKHOUSE_USER


logger = structlog.get_logger(__name__)

GROUPS_DICT_TABLE_NAME = f"{GROUPS_TABLE}_dict"
PERSONS_DICT_TABLE_NAME = f"{PERSONS_TABLE}_dict"
PERSON_DISTINCT_IDS_DICT_TABLE_NAME = f"{PERSON_DISTINCT_ID2_TABLE}_dict"

ALTER_USER_SQL = """
ALTER USER {clickhouse_user}
SETTINGS allow_nondeterministic_mutations = {allow_nondeterministic_mutations}
"""

GROUPS_DICTIONARY_SQL = f"""
CREATE DICTIONARY IF NOT EXISTS {GROUPS_DICT_TABLE_NAME} 
ON CLUSTER '{CLICKHOUSE_CLUSTER}' 
( 
    group_key String, 
    group_properties String
) 
PRIMARY KEY group_key 
SOURCE(CLICKHOUSE(TABLE {GROUPS_TABLE} DB '{CLICKHOUSE_DATABASE}' USER 'default')) 
LAYOUT(complex_key_cache(size_in_cells 1000)) -- 1000000
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
SOURCE(CLICKHOUSE(TABLE person_distinct_id DB '{CLICKHOUSE_DATABASE}' USER 'default')) 
LAYOUT(complex_key_cache(size_in_cells 1000)) -- 50000000
Lifetime(60000)
"""

PERSONS_DICTIONARY_SQL = f"""
CREATE DICTIONARY IF NOT EXISTS {PERSONS_DICT_TABLE_NAME} 
ON CLUSTER '{CLICKHOUSE_CLUSTER}' 
(
    id UUID, 
    properties String
) 
PRIMARY KEY id 
SOURCE(CLICKHOUSE(TABLE person DB '{CLICKHOUSE_DATABASE}' USER 'default')) 
LAYOUT(complex_key_cache(size_in_cells 1000)) -- 5000000
Lifetime(60000)
"""

DROP_GROUPS_DICTIONARY_SQL = f"DROP DICTIONARY IF EXISTS {GROUPS_DICT_TABLE_NAME}"
DROP_PERSON_DISTINCT_IDS_DICTIONARY_SQL = f"DROP DICTIONARY IF EXISTS {PERSON_DISTINCT_IDS_DICT_TABLE_NAME}"
DROP_PERSONS_DICTIONARY_SQL = f"DROP DICTIONARY IF EXISTS {PERSONS_DICT_TABLE_NAME}"


BACKFILL_BASE_SQL = f"""
ALTER TABLE {EVENTS_DATA_TABLE()} 
ON CLUSTER '{CLICKHOUSE_CLUSTER}'
UPDATE 
    person_id=toUUID(dictGet('{PERSON_DISTINCT_IDS_DICT_TABLE_NAME}', 'person_id', distinct_id)),
    person_properties=dictGetString('{PERSONS_DICT_TABLE_NAME}', 'properties', toUUID(dictGet('{PERSON_DISTINCT_IDS_DICT_TABLE_NAME}', 'person_id', distinct_id))),
    group0_properties=dictGetString('{GROUPS_DICT_TABLE_NAME}', 'group_properties', $group_0),
    group1_properties=dictGetString('{GROUPS_DICT_TABLE_NAME}', 'group_properties', $group_1),
    group2_properties=dictGetString('{GROUPS_DICT_TABLE_NAME}', 'group_properties', $group_2),
    group3_properties=dictGetString('{GROUPS_DICT_TABLE_NAME}', 'group_properties', $group_3),
    group4_properties=dictGetString('{GROUPS_DICT_TABLE_NAME}', 'group_properties', $group_4)
"""

query_number = 0


def print_and_execute_query(sql, name, dry_run, timeout=180):
    global query_number

    print(f"> {query_number}. {name}", end="\n\n")
    print(sql, end="\n")
    print("---------------------------------", end="\n\n")

    query_number = query_number + 1

    if not dry_run:
        sync_execute(sql, {"max_execution_time": timeout, "max_memory_usage": 1000000000000})


class Command(BaseCommand):
    help = "Backfill persons and groups data on events for a given team"

    def add_arguments(self, parser):

        parser.add_argument("--team-id", default=None, type=int, help="Specify a team to backfill data for.")

        parser.add_argument(
            "--timeout", default=1000, type=int, help="ClickHouse max_execution_time setting (seconds)."
        )

        parser.add_argument(
            "--live-run", action="store_true", help="Opts out of default 'dry run' mode and actually runs the queries."
        )

    def handle(self, *args, **options):

        if not options["team_id"]:
            logger.error("You must specify --team-id to run this script")
            exit(1)

        BACKFILL_SQL = BACKFILL_BASE_SQL + " WHERE team_id = {team_id}".format(team_id=options["team_id"])
        ALTER_USER_ALLOW_MUTATIONS_SQL = ALTER_USER_SQL.format(
            clickhouse_user=CLICKHOUSE_USER, allow_nondeterministic_mutations=1
        )
        ALTER_USER_DISALLOW_MUTATIONS_SQL = ALTER_USER_SQL.format(
            clickhouse_user=CLICKHOUSE_USER, allow_nondeterministic_mutations=0
        )

        dry_run = not options["live_run"]

        if dry_run:
            print("Dry run. Queries to run:", end="\n\n")

        # print_and_execute_query(ALTER_USER_ALLOW_MUTATIONS_SQL, "ALTER_USER_ALLOW_MUTATIONS_SQL", dry_run)
        print_and_execute_query(GROUPS_DICTIONARY_SQL, "GROUPS_DICTIONARY_SQL", dry_run)
        print_and_execute_query(PERSON_DISTINCT_IDS_DICTIONARY_SQL, "PERSON_DISTINCT_IDS_DICTIONARY_SQL", dry_run)
        print_and_execute_query(PERSONS_DICTIONARY_SQL, "PERSONS_DICTIONARY_SQL", dry_run)
        print_and_execute_query(BACKFILL_SQL, "BACKFILL_SQL", dry_run, options["timeout"])
        # print_and_execute_query(ALTER_USER_DISALLOW_MUTATIONS_SQL, "ALTER_USER_DISALLOW_MUTATIONS_SQL", dry_run)
        print_and_execute_query(DROP_GROUPS_DICTIONARY_SQL, "DROP_GROUPS_DICTIONARY_SQL", dry_run)
        print_and_execute_query(
            DROP_PERSON_DISTINCT_IDS_DICTIONARY_SQL, "DROP_PERSON_DISTINCT_IDS_DICTIONARY_SQL", dry_run
        )
        print_and_execute_query(DROP_PERSONS_DICTIONARY_SQL, "DROP_PERSONS_DICTIONARY_SQL", dry_run)

