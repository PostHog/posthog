-- Staging: 1:1 with source(posthog, events). Clean and type only; no business logic.
-- Parse the few properties your models need out of the JSON blob here, once.
with source as (
    select * from {{ source('posthog', 'events') }}
)
select
    event                                            as event_name,
    distinct_id,
    person_id,
    timestamp::timestamp                             as event_at,
    -- example property extraction; adjust json path to your warehouse's syntax
    json_extract_scalar(properties, '$.$current_url') as current_url,
    json_extract_scalar(properties, '$.$group_0')     as group_key
from source
