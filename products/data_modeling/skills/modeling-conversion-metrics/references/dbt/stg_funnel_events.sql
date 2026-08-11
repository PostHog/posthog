-- Staging: the step events for the funnel, one row per (person, step event), typed and time-bounded.
{{ config(materialized='view') }}

select
    person_id,
    event_name,
    event_at
from {{ ref('stg_events') }}
where event_name in ('signed_up', 'activated', 'purchased')
