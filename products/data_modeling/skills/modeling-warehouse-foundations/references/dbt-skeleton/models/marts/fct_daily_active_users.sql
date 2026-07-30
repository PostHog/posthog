-- Example mart: daily active users. Replace with your domain metric
-- (fct_mrr, fct_conversion, fct_retention, ...). This shows the shape:
-- read from staging, aggregate to the chosen grain, one row per grain key.
with events as (
    select * from {{ ref('stg_events') }}
)
select
    date_trunc('day', event_at) as day,
    count(distinct person_id)   as active_users
from events
group by 1
