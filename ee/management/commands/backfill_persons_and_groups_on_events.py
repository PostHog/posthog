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


logger = structlog.get_logger(__name__)



GROUPS_DICTIONARY_SQL = f"""
CREATE DICTIONARY IF NOT EXISTS {GROUPS_TABLE}_dict 
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
CREATE DICTIONARY IF NOT EXISTS {PERSON_DISTINCT_ID2_TABLE}_dict 
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
CREATE DICTIONARY IF NOT EXISTS {PERSONS_TABLE}_dict 
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


BACKFILL_BASE_SQL = f"""
ALTER TABLE {EVENTS_DATA_TABLE()} 
ON CLUSTER '{CLICKHOUSE_CLUSTER}'
UPDATE 
    person_id=toUUID(dictGet('{PERSON_DISTINCT_ID2_TABLE}_dict', 'person_id', distinct_id)),
    person_properties=dictGetString('{PERSONS_TABLE}_dict', 'properties', toUUID(dictGet('{PERSON_DISTINCT_ID2_TABLE}_dict', 'person_id', distinct_id))),
    group0_properties=dictGetString('{GROUPS_TABLE}_dict', 'group_properties', $group_0),
    group1_properties=dictGetString('{GROUPS_TABLE}_dict', 'group_properties', $group_1),
    group2_properties=dictGetString('{GROUPS_TABLE}_dict', 'group_properties', $group_2),
    group3_properties=dictGetString('{GROUPS_TABLE}_dict', 'group_properties', $group_3),
    group4_properties=dictGetString('{GROUPS_TABLE}_dict', 'group_properties', $group_4)
"""


class Command(BaseCommand):
    help = "Backfill persons and groups data on events for a given team"

    def add_arguments(self, parser):
        
        parser.add_argument(
            "--team-id", default=None, type=int, help="Specify a team to backfill data for."
        )
        
        parser.add_argument(
            "--timeout", default=1000, type=int, help="ClickHouse max_execution_time setting."
        )

    def handle(self, *args, **options):
        
        if not options["team_id"]:
            logger.error("You must specify --team-id to run this script")
            exit(1)
        

        BACKFILL_SQL = BACKFILL_BASE_SQL + " WHERE team_id = {team_id}".format(team_id=options["team_id"]) + " SETTINGS allow_nondeterministic_mutations=1"

            
        print(GROUPS_DICTIONARY_SQL)
        print(PERSON_DISTINCT_IDS_DICTIONARY_SQL)
        print(PERSONS_DICTIONARY_SQL)
        print(BACKFILL_SQL)
        
        sync_execute(GROUPS_DICTIONARY_SQL)
        sync_execute(PERSON_DISTINCT_IDS_DICTIONARY_SQL)
        sync_execute(PERSONS_DICTIONARY_SQL)
        

        sync_execute(BACKFILL_SQL, { "allow_nondeterministic_mutations": 1, "max_execution_time": options['timeout']})




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
        