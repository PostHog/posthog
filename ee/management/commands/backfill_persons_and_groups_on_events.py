import re
from collections import defaultdict
from typing import Dict, Set

import structlog
from django.conf import settings
from django.core.management.base import BaseCommand

from ee.clickhouse.materialized_columns.replication import clickhouse_is_replicated
from ee.clickhouse.sql.events import EVENTS_DATA_TABLE
from ee.clickhouse.sql.groups import GROUPS_TABLE
from ee.clickhouse.sql.person import PERSON_DISTINCT_ID2_TABLE, PERSONS_TABLE
from ee.clickhouse.sql.schema import CREATE_TABLE_QUERIES, get_table_name
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
LAYOUT(complex_key_cache(size_in_cells 1000000))
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
LAYOUT(complex_key_cache(size_in_cells 50000000)) 
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
LAYOUT(complex_key_cache(size_in_cells 5000000)) 
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
        sync_execute(sql, { "max_execution_time": timeout })

class Command(BaseCommand):
    help = "Backfill persons and groups data on events for a given team"

    def add_arguments(self, parser):
        
        parser.add_argument(
            "--team-id", default=None, type=int, help="Specify a team to backfill data for."
        )
        
        parser.add_argument(
            "--timeout", default=1000, type=int, help="ClickHouse max_execution_time setting (seconds)."
        )
        
        parser.add_argument(
            "--dry-run", default=True, type=bool, help="Print statements without running them."
        )


    def handle(self, *args, **options):
        
        if not options["team_id"]:
            logger.error("You must specify --team-id to run this script")
            exit(1)
        

        BACKFILL_SQL = BACKFILL_BASE_SQL + " WHERE team_id = {team_id}".format(team_id=options["team_id"])
        ALTER_USER_ALLOW_MUTATIONS_SQL = ALTER_USER_SQL.format(clickhouse_user=CLICKHOUSE_USER, allow_nondeterministic_mutations=1)
        ALTER_USER_DISALLOW_MUTATIONS_SQL = ALTER_USER_SQL.format(clickhouse_user=CLICKHOUSE_USER, allow_nondeterministic_mutations=0)

        dry_run = options["dry_run"]

        if dry_run:
            print("Dry run. Queries to run:", end="\n\n")

        print_and_execute_query(ALTER_USER_ALLOW_MUTATIONS_SQL, "ALTER_USER_ALLOW_MUTATIONS_SQL", dry_run)        
        print_and_execute_query(GROUPS_DICTIONARY_SQL, "GROUPS_DICTIONARY_SQL", dry_run)
        print_and_execute_query(PERSON_DISTINCT_IDS_DICTIONARY_SQL, "PERSON_DISTINCT_IDS_DICTIONARY_SQL", dry_run)
        print_and_execute_query(PERSONS_DICTIONARY_SQL, "PERSONS_DICTIONARY_SQL", dry_run)
        print_and_execute_query(BACKFILL_SQL, "BACKFILL_SQL", dry_run, options["timeout"])
        print_and_execute_query(ALTER_USER_DISALLOW_MUTATIONS_SQL, "ALTER_USER_DISALLOW_MUTATIONS_SQL", dry_run)
        print_and_execute_query(DROP_GROUPS_DICTIONARY_SQL, "DROP_GROUPS_DICTIONARY_SQL", dry_run)
        print_and_execute_query(DROP_PERSON_DISTINCT_IDS_DICTIONARY_SQL, "DROP_PERSON_DISTINCT_IDS_DICTIONARY_SQL", dry_run)
        print_and_execute_query(DROP_PERSONS_DICTIONARY_SQL, "DROP_PERSONS_DICTIONARY_SQL", dry_run)




"""
        
-- Set up a dictionary for each table we will query, this will issue queries to the underlying table if the 
-- value doesn't exist yet, and will update the cache accordingly

-- Dictionary for `groups` - we get the properties using the existing $group_N materialized columns
CREATE DICTIONARY group_dict ON CLUSTER 'posthog' ( group_key String, group_properties String) 
PRIMARY KEY group_key 
SOURCE(CLICKHOUSE(TABLE groups DB 'default' USER 'default')) 
LAYOUT(complex_key_cache(size_in_cells 10000)) -- currently arbitrary, need to consider this value more carefully
Lifetime(60000) -- same as above

-- Dictionary for `person_distinct_id` - we get the person_id using the distinct_id in the event
CREATE DICTIONARY pdi_dict ON CLUSTER 'posthog' (distinct_id String, person_id UUID) 
PRIMARY KEY distinct_id 
SOURCE(CLICKHOUSE(TABLE person_distinct_id DB 'default' USER 'default')) 
LAYOUT(complex_key_cache(size_in_cells 10000)) 
Lifetime(60000)


-- Dictionary for `person` - we get the properties using the value we 
-- get from fetching the person_id from the distinct_id
CREATE DICTIONARY person_dict ON CLUSTER 'posthog' (id UUID, properties String) 
PRIMARY KEY id 
SOURCE(CLICKHOUSE(TABLE person DB 'default' USER 'default')) 
LAYOUT(complex_key_cache(size_in_cells 10000)) 
Lifetime(60000)

-- This is needed because `dictGet` operations are not deterministic
-- We need to ensure ourselves that the dictionary exists in every node in the cluster (`ON CLUSTER` should do it)
SET allow_nondeterministic_mutations=1

ALTER TABLE sharded_events 
ON CLUSTER 'posthog'
UPDATE 
    person_id=toUUID(dictGet('pdi_dict', 'person_id', distinct_id)),
    -- for person properties we need to do 2 lookups
    person_properties=dictGetString('person_dict', 'properties', toUUID(dictGet('pdi_dict', 'person_id', distinct_id))),
    group0_properties=dictGetString('group_dict', 'group_properties', $group_0),
    group1_properties=dictGetString('group_dict', 'group_properties', $group_1),
    group2_properties=dictGetString('group_dict', 'group_properties', $group_2),
    group3_properties=dictGetString('group_dict', 'group_properties', $group_3),
    group4_properties=dictGetString('group_dict', 'group_properties', $group_4)
WHERE 1
        """
        