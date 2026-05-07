ALTER TABLE sharded_events MODIFY COLUMN             properties_group_ai Map(String, String)
            MATERIALIZED mapSort(
                mapFilter((key, _) -> key LIKE '$ai_%' AND key NOT IN ('$ai_input', '$ai_input_state', '$ai_output', '$ai_output_choices', '$ai_output_state', '$ai_tools'),
                CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)'))
            )
            CODEC(ZSTD(1))
        , ADD INDEX IF NOT EXISTS properties_group_ai_keys_bf mapKeys(properties_group_ai) TYPE bloom_filter, ADD INDEX IF NOT EXISTS properties_group_ai_values_bf mapValues(properties_group_ai) TYPE bloom_filter

ALTER TABLE events MODIFY COLUMN properties_group_ai Map(String, String)
