from infi.clickhouse_orm import migrations

EVENTS_WITH_PROPS_SQL = """
CREATE MATERIALIZED VIEW default.events_with_array_props_view
ENGINE = MergeTree()
ORDER BY (team_id, created_at, id)
PARTITION BY toYYYYMM(timestamp)
SAMPLE BY id
POPULATE
AS SELECT
id,
event,
properties,
arrayMap(k -> k.1, JSONExtractKeysAndValues(properties, 'varchar')) array_property_keys,
arrayMap(k -> k.2, JSONExtractKeysAndValues(properties, 'varchar')) array_property_values,
timestamp,
team_id,
distinct_id,
elements_hash,
created_at,
JSONExtractString(properties, '$ip'),
JSONExtractString(properties, 'distinct_id') ,
JSONExtractString(properties, '$current_url') ,
JSONExtractString(properties, 'modalName') ,
JSONExtractString(properties, 'currentScreen') ,
JSONExtractString(properties, 'networkType') ,
JSONExtractString(properties, 'referralScreen') ,
JSONExtractString(properties, 'sessionId') ,
JSONExtractString(properties, '$lib_version') ,
JSONExtractString(properties, '$lib') ,
JSONExtractString(properties, 'activeExperimentNames') ,
JSONExtractString(properties, '$initial_referrer') ,
JSONExtractString(properties, '$initial_referring_domain') ,
JSONExtractString(properties, '$device_id') ,
JSONExtractString(properties, '$insert_id') ,
JSONExtractString(properties, 'token') ,
JSONExtractString(properties, '$browser') ,
JSONExtractString(properties, '$os') ,
JSONExtractString(properties, '$pathname') ,
JSONExtractString(properties, '$host') ,
JSONExtractString(properties, '$event_type') ,
JSONExtractString(properties, '$referrer') ,
JSONExtractString(properties, '$referring_domain') ,
JSONExtractString(properties, 'objectName') ,
JSONExtractString(properties, '$device') ,
JSONExtractString(properties, '$search_engine') ,
JSONExtractString(properties, 'context') ,
JSONExtractString(properties, 'method') ,
JSONExtractString(properties, '$user_id') ,
JSONExtractString(properties, 'objectValue') ,
JSONExtractString(properties, 'context_1_name') ,
JSONExtractString(properties, 'utm_source') ,
JSONExtractString(properties, 'utm_medium') ,
JSONExtractString(properties, 'utm_campaign') ,
JSONExtractString(properties, 'context_1_value') ,
JSONExtractString(properties, 'View name') ,
JSONExtractString(properties, 'context_2_name') ,
JSONExtractString(properties, 'utm_content') ,
JSONExtractString(properties, 'context_3_name') ,
JSONExtractString(properties, 'context_4_name') ,
JSONExtractString(properties, 'context_5_name') ,
JSONExtractString(properties, 'utm_term') ,
JSONExtractString(properties, 'plan') ,
JSONExtractString(properties, '$email') ,
JSONExtractString(properties, '$name') ,
JSONExtractString(properties, 'Signed Up') ,
JSONExtractString(properties, '$created') ,
JSONExtractString(properties, 'searchTerm') ,
JSONExtractString(properties, 'searchId') ,
JSONExtractString(properties, 'name')
FROM default.events;
"""

PROP_SQL = """
CREATE MATERIALIZED VIEW default.events_properties_view
ENGINE = MergeTree()
ORDER BY (team_id, key, value, event_id)
POPULATE
AS SELECT id as event_id,
team_id,
array_property_keys as key,
array_property_values as value
from default.events_with_array_props_view
ARRAY JOIN array_property_keys, array_property_values
"""

operations = [
    migrations.RunSQL(EVENTS_WITH_PROPS_SQL),
    migrations.RunSQL(PROP_SQL),
]
