select
    uuid as uuid,
    distinct_id as distinct_id,
    event as event,
    team_id,
    set as set,
    set_once as set_once,
    properties.$ip as ip,
    toJSONString(elements_chain) as elements,
    '' as site_url,
    timestamp as timestamp,
    created_at as created_at,
    properties as properties,
    now() as bq_ingested_timestamp
from
    events_batch_export
