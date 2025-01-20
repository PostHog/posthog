select
    uuid as uuid,
    timestamp as timestamp,
    event as event,
    properties as properties,
    distinct_id as distinct_id,
    elements_chain as elements_chain
from
    events_batch_export
