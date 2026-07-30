-- Line-item grain revenue fact, the dbt analogue of PostHog's managed revenue_item view.
-- Converts each line item to the reporting base currency via the currency_rates seed
-- (dbt has no convertCurrency()). Config it as incremental once history is large.
{{ config(materialized='table') }}

with items as (
    select * from {{ source('stripe', 'invoice_line_items') }}
),
rates as (
    select currency, rate_date, rate_to_base from {{ ref('currency_rates') }}
)
select
    i.id                                             as revenue_item_id,
    i.subscription_id,
    i.customer_id,
    i.product_id,
    i.period_start::date                             as period_start,
    i.period_end::date                               as period_end,
    date_trunc('month', i.period_start)              as month,
    i.subscription_id is not null                    as is_recurring,
    i.currency                                       as original_currency,
    i.amount                                         as original_amount,
    -- amount in base currency at the item's rate:
    i.amount * coalesce(r.rate_to_base, 1.0)         as amount
from items i
left join rates r
    on r.currency = i.currency
   and r.rate_date = i.period_start::date
