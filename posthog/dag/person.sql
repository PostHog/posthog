insert into posthog_dag.person

-- Example of the logic:
--  (set_once1, set_once2) -> set_once1
--  (set1, set2) -> set2
--  (set_once1, set_once2, set1) -> set1
--  (set1, set_once1, set_once2) -> set1
--  (set_once1, set1, set_once2) -> set1

-- We always want the latest $set. If there are no sets we want the first $set_once
with 

events_with_person as (
    select
        JSONExtractKeysAndValuesRaw(JSONExtractRaw(properties, '$set')) as extracted,
        JSONExtractKeysAndValuesRaw(JSONExtractRaw(properties, '$set_once')) as extracted_2,
        pid.is_identified as is_identified,
        arrayMap(x -> x.1, extracted) as keys,
        arrayMap(x -> (x.2, timestamp, 0, is_identified), extracted) as values,
        arrayZip(
            keys,
            values 
        ) one,
        -- Remove properties in set_once that are also in set, as they'll never be used, and simplifies query later
        arrayFilter(x -> not isNull(x.1), arrayMap(x -> if(has(keys, x.1), (null, null), x), extracted_2)) as uniq_set_once,
        arrayZip(
            arrayMap(x -> x.1, uniq_set_once),
            arrayMap(x -> (x.2, timestamp, 1, is_identified), uniq_set_once)
        ) two,
        arrayConcat(one, two) as three,
        (arrayJoin(three) AS t).1 AS _keys,
        t.2 AS _values,
        pid.person_id as person_id,
        events.team_id as team_id,
        timestamp
    from
        events
    inner join
        posthog_dag.person_distinct_id pid ON (pid.distinct_id=events.distinct_id and pid.team_id=events.team_id)
),
correct_value_for_each_key as (
    select
        _keys as key,
        groupArray(_values) as values,
        arraySort(x -> (x.4, x.2), arrayFilter(x -> x.3 = 1, values)) as set_once_values,
        arrayReverseSort(x -> (x.4*-1, x.2), arrayFilter(x -> x.3 = 0, values)) as set_values,
        replaceRegexpAll(
            if(
                notEmpty(set_values),
                set_values[1].1,
                set_once_values[1].1
            ),
            '^\"|\"$', '') as value,
        person_id,
        team_id,
        min(timestamp) as created_at
    from events_with_person
    group by _keys, person_id, team_id
),
persons_with_properties as (
    select
        person_id as id,
        min(created_at) as created_at,
        team_id,
        toJSONString(
            -- Replace with mapFromArrays(groupArray(_keys), groupArray(values))) after clickhouse 2.23
            CAST((groupArray(key), groupArray(value)), 'Map(String, String)')
        ) as properties
    from correct_value_for_each_key
    group by person_id, team_id

)

select
    person_id as id,
    -- TODO: grab created_at from person_distinct_id if no properties exist?
    coalesce(persons_with_properties.created_at, 0) as created_at,
    team_id,
    coalesce(persons_with_properties.properties, '{}') as properties,
    0 as is_identified,
    0 as is_deleted,
    0 as version,
    now() as _timestamp,
    0 as _offset
from (
    select
        person_id,
        team_id
    from
        posthog_dag.person_distinct_id
    group by person_id, team_id
) pid
left outer join persons_with_properties on (persons_with_properties.id=pid.person_id)