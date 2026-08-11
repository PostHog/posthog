-- Per-user activation flag + activated_at, driven by dim_activation_criteria.
-- activated_at is the timestamp of the threshold-crossing (min_count-th) qualifying action within the
-- window — the moment the user actually activated — not their first action.
{{ config(materialized='table') }}

with criteria as (
    select action_event, min_count, window_days from {{ ref('dim_activation_criteria') }}
),
first_seen as (
    select person_id, min(event_at) as signup_at
    from {{ ref('stg_events') }}
    group by person_id
),
qualifying as (
    -- key actions inside the early window, ranked per person by time
    select
        e.person_id,
        e.event_at,
        row_number() over (partition by e.person_id order by e.event_at) as rn
    from {{ ref('stg_events') }} e
    join first_seen f using (person_id)
    cross join criteria c
    where e.event_name = c.action_event
      and e.event_at <= f.signup_at + (c.window_days || ' day')::interval
),
crossed as (
    -- the min_count-th qualifying action = the activation moment
    select q.person_id, q.event_at as activated_at
    from qualifying q
    cross join criteria c
    where q.rn = c.min_count
)
select
    f.person_id,
    f.signup_at,
    x.person_id is not null as is_activated,
    x.activated_at
from first_seen f
left join crossed x using (person_id)
