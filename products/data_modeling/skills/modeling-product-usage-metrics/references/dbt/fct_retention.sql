-- Weekly retention matrix (recurring). Warehouse-agnostic; adjust date_trunc/date_diff to your warehouse.
{{ config(materialized='table') }}

with activity as (
    select distinct
        person_id,
        date_trunc('week', event_at) as week
    from {{ ref('stg_events') }}
    where event_name = 'core_action'
),
cohort as (
    select person_id, min(week) as cohort_week
    from activity
    group by person_id
),
joined as (
    select
        c.cohort_week,
        a.person_id,
        ({{ 'datediff' }}('week', c.cohort_week, a.week)) as weeks_later
    from cohort c
    join activity a using (person_id)
    where a.week >= c.cohort_week
)
select
    cohort_week,
    weeks_later,
    count(distinct person_id) as retained,
    count(distinct person_id)::numeric
        / max(count(distinct person_id)) over (partition by cohort_week) as retention_rate
from joined
group by cohort_week, weeks_later
