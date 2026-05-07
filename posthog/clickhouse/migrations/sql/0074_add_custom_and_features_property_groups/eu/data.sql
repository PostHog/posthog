ALTER TABLE sharded_events ADD COLUMN IF NOT EXISTS             properties_group_custom Map(String, String)
            MATERIALIZED mapSort(
                mapFilter((key, _) -> key NOT LIKE '$%' AND key NOT IN ('token', 'distinct_id', 'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'gclid', 'gad_source', 'gclsrc', 'dclid', 'gbraid', 'wbraid', 'fbclid', 'msclkid', 'twclid', 'li_fat_id', 'mc_cid', 'igshid', 'ttclid', 'rdt_cid', 'epik', 'qclid', 'sccid', 'irclid', '_kx'),
                CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)'))
            )
            CODEC(ZSTD(1))
        , ADD INDEX IF NOT EXISTS properties_group_custom_keys_bf mapKeys(properties_group_custom) TYPE bloom_filter, ADD INDEX IF NOT EXISTS properties_group_custom_values_bf mapValues(properties_group_custom) TYPE bloom_filter

ALTER TABLE sharded_events ADD COLUMN IF NOT EXISTS             properties_group_feature_flags Map(String, String)
            MATERIALIZED mapSort(
                mapFilter((key, _) -> key like '$feature/%',
                CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)'))
            )
            CODEC(ZSTD(1))
        , ADD INDEX IF NOT EXISTS properties_group_feature_flags_keys_bf mapKeys(properties_group_feature_flags) TYPE bloom_filter, ADD INDEX IF NOT EXISTS properties_group_feature_flags_values_bf mapValues(properties_group_feature_flags) TYPE bloom_filter
