select
    uuid as uuid,
    person_id as person_id,
    person_properties as person_properties,
    timestamp as timestamp,
    created_at as created_at,
    event as event,
    properties as properties,
    distinct_id as distinct_id,
from
    events
