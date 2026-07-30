-- Per-user activation flag + activated_at, driven by dim_activation_criteria.
{{ config(materialized='table') }}

with criteria as (
    select action_event, min_count, window_days from {{ ref('dim_activation_criteria') }}
),
first_seen as (
    select person_id, min(event_at) as signup_at
    from {{ ref('stg_events') }}
    group by person_id
),
early as (
    select
        e.person_id,
        count(*) filter (
            where e.event_name = (select action_event from criteria)
              and e.event_at <= f.signup_at + ((select window_days from criteria) || ' day')::interval
        ) as early_count,
        min(e.event_at) filter (
            where e.event_name = (select action_event from criteria)
        ) as first_action_at
    from {{ ref('stg_events') }} e
    join first_seen f using (person_id)
    group by e.person_id
)
select
    f.person_id,
    f.signup_at,
    coalesce(e.early_count, 0) >= (select min_count from criteria) as is_activated,
    e.first_action_at                                             as activated_at
from first_seen f
left join early e using (person_id)
