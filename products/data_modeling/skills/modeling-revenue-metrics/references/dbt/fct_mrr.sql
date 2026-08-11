-- Monthly MRR + the movement bridge (new / expansion / contraction / churn), built on fct_revenue_item.
-- A dense customer x month spine is essential: without a row for every month, lag() would compare a
-- customer's last active month to their NEXT active month and silently skip the churn in between.
-- Validation identity: starting_mrr + new + expansion - contraction - churn = ending_mrr.
{{ config(materialized='table') }}

with monthly as (
    select
        customer_id,
        month,
        sum(amount) as mrr
    from {{ ref('fct_revenue_item') }}
    where is_recurring
    group by 1, 2
),
months as (
    select distinct month from monthly  -- observed month range (swap for a generate_series spine if needed)
),
customers as (
    select distinct customer_id from monthly
),
filled as (
    -- one row per customer per month, zero-filled, so churn shows up as mrr -> 0
    select
        c.customer_id,
        m.month,
        coalesce(mo.mrr, 0) as mrr
    from customers c
    cross join months m
    left join monthly mo
        on mo.customer_id = c.customer_id
       and mo.month = m.month
),
with_prev as (
    select
        customer_id,
        month,
        mrr,
        lag(mrr) over (partition by customer_id order by month) as prev_mrr
    from filled
)
select
    month,
    sum(mrr)                                                               as mrr,
    sum(mrr) * 12                                                          as arr,
    sum(case when coalesce(prev_mrr, 0) = 0 and mrr > 0 then mrr else 0 end)      as new_mrr,
    sum(case when prev_mrr > 0 and mrr > prev_mrr then mrr - prev_mrr else 0 end) as expansion_mrr,
    sum(case when mrr > 0 and mrr < prev_mrr then prev_mrr - mrr else 0 end)      as contraction_mrr,
    sum(case when prev_mrr > 0 and mrr = 0 then prev_mrr else 0 end)              as churned_mrr
from with_prev
group by month
order by month
