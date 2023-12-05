import json
import os

from posthog.settings import CLICKHOUSE_CLUSTER

CHANNEL_DEFINITION_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS channel_definition ON CLUSTER {CLICKHOUSE_CLUSTER} (
    domain String,
    type String
) ENGINE = MergeTree()
ORDER BY domain;
"""

DROP_CHANNEL_DEFINITION_TABLE_SQL = f"DROP TABLE IF EXISTS channel_definition ON CLUSTER '{CLICKHOUSE_CLUSTER}'"

TRUNCATE_CHANNEL_DEFINITION_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS channel_definition ON CLUSTER '{CLICKHOUSE_CLUSTER}'"

with open(os.path.join(os.path.dirname(__file__), "channel_definitions.json"), "r") as f:
    CHANNEL_DEFINITIONS = json.loads(f.read())

CHANNEL_DEFINITIONS_DATA_SQL = f"""
INSERT INTO channel_definition (domain, type) VALUES
{
''',
'''.join(map(lambda x: f"('{x[0]}', '{x[1]}')", CHANNEL_DEFINITIONS))},
;
"""

# Use COMPLEX_KEY_HASHED, even though we only have one key, because it's the only way to get a dictionary to work with
# a primary key that's a string
CHANNEL_DEFINITION_DICTIONARY_SQL = """
CREATE DICTIONARY IF NOT EXISTS channel_definition_dict (
    domain String,
    type String
)
PRIMARY KEY domain
SOURCE(CLICKHOUSE(TABLE 'channel_definition'))
LIFETIME(MIN 1 MAX 3600)
LAYOUT(COMPLEX_KEY_HASHED())
"""

DROP_CHANNEL_DEFINITION_DICTIONARY_SQL = (
    f"DROP DICTIONARY IF EXISTS channel_definition_dict ON CLUSTER '{CLICKHOUSE_CLUSTER}'"
)
