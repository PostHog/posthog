from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

operations = [
    run_sql_with_exceptions(statement)
    for statement in [
        "ALTER TABLE sharded_events ADD COLUMN properties_map Map(String, String) ALIAS CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)')",
        "ALTER TABLE sharded_events MODIFY COLUMN properties_group_custom MATERIALIZED mapFilter((key, _) -> key NOT LIKE '$%' AND key NOT IN ('token', 'distinct_id', 'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'gclid', 'gad_source', 'gclsrc', 'dclid', 'gbraid', 'wbraid', 'fbclid', 'msclkid', 'twclid', 'li_fat_id', 'mc_cid', 'igshid', 'ttclid', 'rdt_cid'), properties_map)",
        "ALTER TABLE sharded_events MODIFY COLUMN properties_group_feature_flags MATERIALIZED mapFilter((key, _) -> key like '$feature/%', properties_map)",
    ]
]
