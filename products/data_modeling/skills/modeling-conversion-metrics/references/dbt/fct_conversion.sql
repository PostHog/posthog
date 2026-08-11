-- Warehouse-agnostic funnel with step ordering AND a conversion window, in plain SQL — the dbt
-- analogue of windowFunnel. Each step is the EARLIEST occurrence AFTER the previous step's timestamp
-- (and within N days of step 1), so a valid ordered chain survives even when an out-of-order event
-- happens to be earlier — which an independent per-step min() would wrongly pick.
-- 14-day window shown; adjust the interval literal to your warehouse's syntax.
{{ config(materialized='table') }}

with events as (
    select person_id, event_name, event_at from {{ ref('stg_funnel_events') }}
),
step1 as (
    select person_id, min(event_at) as t_signup
    from events
    where event_name = 'signed_up'
    group by person_id
),
step2 as (
    -- first activation at/after signup and within the window
    select s.person_id, s.t_signup, min(e.event_at) as t_activated
    from step1 s
    join events e
        on e.person_id = s.person_id
       and e.event_name = 'activated'
       and e.event_at between s.t_signup and s.t_signup + interval '14 day'
    group by s.person_id, s.t_signup
),
step3 as (
    -- first purchase at/after activation and still within the window from signup
    select a.person_id, min(e.event_at) as t_purchased
    from step2 a
    join events e
        on e.person_id = a.person_id
       and e.event_name = 'purchased'
       and e.event_at between a.t_activated and a.t_signup + interval '14 day'
    group by a.person_id
)
select
    count(s1.person_id)                                                     as entered_step_1,
    count(s2.person_id)                                                     as reached_activated,
    count(s3.person_id)                                                     as reached_purchased,
    round(count(s3.person_id)::numeric / nullif(count(s1.person_id), 0), 4) as overall_conversion
from step1 s1
left join step2 s2 using (person_id)
left join step3 s3 using (person_id)
