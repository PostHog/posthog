SELECT
    team_id,
    uuid AS event_uuid,
    concat('{', arrayStringConcat(arrayMap(
        property -> concat(toJSONString(property.1), ':', property.2),
        arrayFilter(property -> property.1 IN ('$set', '$set_once', '$unset'),
            JSONExtractKeysAndValuesRaw(source.properties))
    ), ','), '}') AS properties,
    toDateTime(_timestamp, 'UTC') AS ingested_at
FROM kafka_person_property_mutation_log AS source
WHERE JSONHas(source.properties, '$set') OR JSONHas(source.properties, '$set_once') OR JSONHas(source.properties, '$unset')
