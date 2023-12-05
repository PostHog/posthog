import json
import os

from posthog.settings import CLICKHOUSE_CLUSTER

GA4_CHANNEL_DEFINITION_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS ga4_channel_definition ON CLUSTER {CLICKHOUSE_CLUSTER} (
    domain String,
    type String
) ENGINE = MergeTree()
ORDER BY domain;
"""

DROP_GA4_CHANNEL_DEFINITION_TABLE_SQL = f"DROP TABLE IF EXISTS ga4_channel_definition ON CLUSTER '{CLICKHOUSE_CLUSTER}'"

TRUNCATE_GA4_CHANNEL_DEFINITION_TABLE_SQL = (
    lambda: f"TRUNCATE TABLE IF EXISTS ga4_channel_definition ON CLUSTER '{CLICKHOUSE_CLUSTER}'"
)

with open(os.path.join(os.path.dirname(__file__), "ga4_channel_definitions.json"), "r") as f:
    GA_CHANNEL_DEFINITIONS = json.loads(f.read())

GA_CHANNEL_DEFINITIONS_DATA_SQL = f"""
INSERT INTO ga4_channel_definition (domain, type) VALUES
{
''',
'''.join(map(lambda x: f"('{x[0]}', '{x[1]}')", GA_CHANNEL_DEFINITIONS))},
;
"""

# Use COMPLEX_KEY_HASHED, even though we only have one key, because it's the only way to get a dictionary to work with
# a primary key that's a string
GA4_CHANNEL_DEFINITION_DICTIONARY_SQL = """
CREATE DICTIONARY IF NOT EXISTS ga4_channel_definition_dict (
    domain String,
    type String
)
PRIMARY KEY domain
SOURCE(CLICKHOUSE(TABLE 'ga4_channel_definition'))
LIFETIME(MIN 1 MAX 3600)
LAYOUT(COMPLEX_KEY_HASHED())
"""

DROP_GA4_CHANNEL_DEFINITION_DICTIONARY_SQL = (
    f"DROP DICTIONARY IF EXISTS ga4_channel_definition_dict ON CLUSTER '{CLICKHOUSE_CLUSTER}'"
)
