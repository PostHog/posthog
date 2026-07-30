-- Warehouse-agnostic funnel: compute each person's first timestamp per step, then apply the
-- conversion-window rule AND step ordering (signup <= activated <= purchased, all within N days of
-- signup) using plain SQL — matching what windowFunnel enforces on the PostHog side.
-- 14-day window shown; adjust the interval literal to your warehouse's syntax.
{{ config(materialized='table') }}

with steps as (
    select
        person_id,
        min(case when event_name = 'signed_up' then event_at end) as t_signup,
        min(case when event_name = 'activated' then event_at end) as t_activated,
        min(case when event_name = 'purchased' then event_at end) as t_purchased
    from {{ ref('stg_funnel_events') }}
    group by person_id
),
flags as (
    select
        person_id,
        t_signup is not null as entered,
        -- step 2 must land in [signup, signup + window]
        (t_activated is not null
         and t_activated between t_signup and t_signup + interval '14 day') as reached_activated,
        -- step 3 must come AFTER step 2 (ordering) and still inside the window from signup
        (t_activated is not null
         and t_activated between t_signup and t_signup + interval '14 day'
         and t_purchased is not null
         and t_purchased between t_activated and t_signup + interval '14 day') as reached_purchased
    from steps
    where t_signup is not null
)
select
    count(*)                                                            as entered_step_1,
    sum(case when reached_activated then 1 else 0 end)                  as reached_activated,
    sum(case when reached_purchased then 1 else 0 end)                 as reached_purchased,
    round(sum(case when reached_purchased then 1 else 0 end)::numeric
          / nullif(count(*), 0), 4)                                     as overall_conversion
from flags
