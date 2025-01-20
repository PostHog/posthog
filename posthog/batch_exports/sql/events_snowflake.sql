select
    uuid as uuid,
    distinct_id as distinct_id,
    event as event,
    team_id,
    set as people_set,
    set_once as people_set_once,
    properties.$ip as ip,
    elements_chain as elements,
    '' as site_url,
    timestamp as timestamp,
    created_at as created_at,
    properties as properties
from
    events_batch_export
