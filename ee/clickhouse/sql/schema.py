# This file contains all CREATE TABLE queries, used to sync and test schema
import re

from ee.clickhouse.sql.cohort import *
from ee.clickhouse.sql.dead_letter_queue import *
from ee.clickhouse.sql.events import *
from ee.clickhouse.sql.groups import *
from ee.clickhouse.sql.person import *
from ee.clickhouse.sql.plugin_log_entries import *
from ee.clickhouse.sql.session_recording_events import *

CREATE_TABLE_QUERIES = [
    CREATE_COHORTPEOPLE_TABLE_SQL,
    PERSON_STATIC_COHORT_TABLE_SQL,
    DEAD_LETTER_QUEUE_TABLE_SQL,
    KAFKA_DEAD_LETTER_QUEUE_TABLE_SQL,
    DEAD_LETTER_QUEUE_TABLE_MV_SQL,
    EVENTS_TABLE_SQL,
    KAFKA_EVENTS_TABLE_SQL,
    EVENTS_TABLE_MV_SQL,
    GROUPS_TABLE_SQL,
    KAFKA_GROUPS_TABLE_SQL,
    GROUPS_TABLE_MV_SQL,
    PERSONS_TABLE_SQL,
    KAFKA_PERSONS_TABLE_SQL,
    PERSONS_TABLE_MV_SQL,
    PERSONS_DISTINCT_ID_TABLE_SQL,
    KAFKA_PERSONS_DISTINCT_ID_TABLE_SQL,
    PERSONS_DISTINCT_ID_TABLE_MV_SQL,
    PERSON_DISTINCT_ID2_TABLE_SQL,
    KAFKA_PERSON_DISTINCT_ID2_TABLE_SQL,
    PERSON_DISTINCT_ID2_MV_SQL,
    KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL,
    PLUGIN_LOG_ENTRIES_TABLE_SQL,
    PLUGIN_LOG_ENTRIES_TABLE_MV_SQL,
    SESSION_RECORDING_EVENTS_TABLE_SQL,
    KAFKA_SESSION_RECORDING_EVENTS_TABLE_SQL,
    SESSION_RECORDING_EVENTS_TABLE_MV_SQL,
    WRITABLE_EVENTS_TABLE_SQL,
    DISTRIBUTED_EVENTS_TABLE_SQL,
    WRITABLE_SESSION_RECORDING_EVENTS_TABLE_SQL,
    DISTRIBUTED_SESSION_RECORDING_EVENTS_TABLE_SQL,
]

build_query = lambda query: query if isinstance(query, str) else query()
get_table_name = lambda query: re.findall(r" ([a-z0-9_]+) ON CLUSTER", build_query(query))[0]
