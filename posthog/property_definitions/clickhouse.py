# rust/property-defs-rs/src/types.rs::detect_property_type
DETECT_PROPERTY_TYPE_EXPR = """
    arrayMap(
        (name, value) -> (name, multiIf(
            -- special cases: key patterns
            name ilike 'utm_%', 'String',
            name ilike '$feature/%', 'String',
            name ilike '$feature_flag_response', 'String',
            name ilike '$survey_response%', 'String',
            -- special cases: timestamp detection
            (
                multiSearchAnyCaseInsensitive(name, ['time', 'timestamp', 'date', '_at', '-at', 'createdat', 'updatedat'])
                AND JSONType(value) IN ('Int64', 'UInt64', 'Double')
                AND JSONExtract(value, 'Nullable(Float)') >= toUnixTimestamp(now() - interval '6 months')
            ), 'DateTime',
            -- special cases: string value patterns
            (
                JSONType(value) = 'String'
                AND trimBoth(JSONExtractString(value)) IN ('true', 'TRUE', 'false', 'FALSE')
            ), 'Boolean',
            (
                JSONType(value) = 'String'
                AND length(trimBoth(JSONExtractString(value)) as trimmed_value) >= 10  -- require at least a date part
                AND parseDateTime64BestEffortOrNull(trimmed_value) IS NOT NULL  -- can be parsed as a date
                AND JSONExtract(trimmed_value, 'Nullable(Float)') IS NULL  -- but not as a timestamp
            ), 'DateTime',
            -- primitive types
            JSONType(value) = 'Bool', 'Boolean',
            JSONType(value) = 'String', 'String',
            JSONType(value) IN ('Int64', 'UInt64', 'Double'), 'Numeric',
            NULL
        )),
        JSONExtractKeysAndValuesRaw(properties)
    )
"""
