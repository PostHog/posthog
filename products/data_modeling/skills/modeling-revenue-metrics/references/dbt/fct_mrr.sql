-- Monthly MRR + the movement bridge (new / expansion / contraction / churn), built on fct_revenue_item.
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
with_prev as (
    select
        customer_id,
        month,
        mrr,
        lag(mrr) over (partition by customer_id order by month) as prev_mrr
    from monthly
)
select
    month,
    sum(mrr)                                                             as mrr,
    sum(mrr) * 12                                                        as arr,
    sum(case when coalesce(prev_mrr,0)=0 and mrr>0 then mrr else 0 end)  as new_mrr,
    sum(case when prev_mrr>0 and mrr>prev_mrr then mrr-prev_mrr else 0 end) as expansion_mrr,
    sum(case when mrr>0 and mrr<prev_mrr then prev_mrr-mrr else 0 end)   as contraction_mrr,
    sum(case when prev_mrr>0 and mrr=0 then prev_mrr else 0 end)         as churned_mrr
from with_prev
group by month
order by month
