ALTER TABLE sharded_events ADD COLUMN IF NOT EXISTS             person_properties_map_custom Map(String, String)
            MATERIALIZED mapSort(
                mapFilter((key, _) -> key NOT LIKE '$%',
                CAST(JSONExtractKeysAndValues(person_properties, 'String'), 'Map(String, String)'))
            )
            CODEC(ZSTD(1))
        , ADD INDEX IF NOT EXISTS person_properties_map_custom_keys_bf mapKeys(person_properties_map_custom) TYPE bloom_filter, ADD INDEX IF NOT EXISTS person_properties_map_custom_values_bf mapValues(person_properties_map_custom) TYPE bloom_filter

ALTER TABLE events ADD COLUMN IF NOT EXISTS person_properties_map_custom Map(String, String)
