-- Lifecycle: per person-week status (new / returning / resurrecting). Dormant is derived downstream.
{{ config(materialized='table') }}

with activity as (
    select distinct
        person_id,
        date_trunc('week', event_at) as week
    from {{ ref('stg_events') }}
    where event_name = 'core_action'
),
enriched as (
    select
        person_id,
        week,
        min(week) over (partition by person_id) as first_week,
        lag(week) over (partition by person_id order by week) as prev_week
    from activity
)
select
    week,
    count(*) filter (where week = first_week)                                              as new_users,
    count(*) filter (where week <> first_week and prev_week = week - interval '1 week')     as returning_users,
    count(*) filter (where week <> first_week and (prev_week is null or prev_week < week - interval '1 week')) as resurrecting_users
from enriched
group by week
order by week
