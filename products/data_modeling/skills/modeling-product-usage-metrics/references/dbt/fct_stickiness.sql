-- Stickiness distribution: users by number of active days in the trailing 30-day window.
{{ config(materialized='table') }}

with per_person as (
    select
        person_id,
        count(distinct date_trunc('day', event_at)) as active_days
    from {{ ref('stg_events') }}
    where event_name = 'core_action'
      and event_at >= current_date - interval '30 day'
    group by person_id
)
select
    active_days as active_days_in_period,
    count(*)    as users
from per_person
group by active_days
order by active_days
