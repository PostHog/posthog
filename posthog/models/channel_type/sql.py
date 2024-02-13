import json
import os

from posthog.clickhouse.table_engines import (
    MergeTreeEngine,
    ReplicationScheme,
)
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_PASSWORD

CHANNEL_DEFINITION_TABLE_NAME = "channel_definition"
CHANNEL_DEFINITION_DICTIONARY_NAME = "channel_definition_dict"

CHANNEL_DEFINITION_TABLE_SQL = (
    lambda: """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}' (
    domain String NOT NULL,
    kind String NOT NULL,
    domain_type String NULL,
    type_if_paid String NULL,
    type_if_organic String NULL
) ENGINE = {engine}
ORDER BY (domain, kind);
""".format(
        table_name=CHANNEL_DEFINITION_TABLE_NAME,
        engine=MergeTreeEngine("channel_definition", replication_scheme=ReplicationScheme.REPLICATED),
        cluster=CLICKHOUSE_CLUSTER,
    )
)


DROP_CHANNEL_DEFINITION_TABLE_SQL = (
    f"DROP TABLE IF EXISTS {CHANNEL_DEFINITION_TABLE_NAME} ON CLUSTER '{CLICKHOUSE_CLUSTER}'"
)


TRUNCATE_CHANNEL_DEFINITION_TABLE_SQL = (
    f"TRUNCATE TABLE IF EXISTS {CHANNEL_DEFINITION_TABLE_NAME} ON CLUSTER '{CLICKHOUSE_CLUSTER}'"
)

with open(os.path.join(os.path.dirname(__file__), "channel_definitions.json"), "r") as f:
    CHANNEL_DEFINITIONS = json.loads(f.read())


def format_value(value):
    if value is None:
        return "NULL"
    elif isinstance(value, str):
        return f"'{value}'"
    else:
        raise ValueError(f"Unknown value type {type(value)}")


CHANNEL_DEFINITION_DATA_SQL = f"""
INSERT INTO channel_definition (domain, kind, domain_type, type_if_paid, type_if_organic) VALUES
{
''',
'''.join(map(lambda x: f'({" ,".join(map(format_value, x))})', CHANNEL_DEFINITIONS))},
;
"""

# Use COMPLEX_KEY_HASHED, as we have a composite key
CHANNEL_DEFINITION_DICTIONARY_SQL = f"""
CREATE DICTIONARY IF NOT EXISTS {CHANNEL_DEFINITION_DICTIONARY_NAME} ON CLUSTER '{CLICKHOUSE_CLUSTER}' (
    domain String,
    kind String,
    domain_type Nullable(String),
    type_if_paid Nullable(String),
    type_if_organic Nullable(String)
)
PRIMARY KEY domain, kind
SOURCE(CLICKHOUSE(TABLE '{CHANNEL_DEFINITION_TABLE_NAME}' PASSWORD '{CLICKHOUSE_PASSWORD}'))
LIFETIME(MIN 3000 MAX 3600)
LAYOUT(COMPLEX_KEY_HASHED())
"""

DROP_CHANNEL_DEFINITION_DICTIONARY_SQL = (
    f"DROP DICTIONARY IF EXISTS {CHANNEL_DEFINITION_DICTIONARY_NAME} ON CLUSTER '{CLICKHOUSE_CLUSTER}'"
)
