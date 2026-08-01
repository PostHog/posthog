-- Line-item grain revenue fact, the dbt analogue of PostHog's managed revenue_item view.
-- Recognizes deferred revenue: each recurring line item is spread evenly across the calendar months
-- of its service period [period_start, period_end], so an annual plan feeds 1/12 of its value into
-- each month's MRR rather than the whole amount into a single month. One-time (non-subscription)
-- items resolve to just the month they were charged. Grain is one row per (line item, service month).
-- Converts to the reporting base currency via the currency_rates seed (dbt has no convertCurrency()).
{{ config(materialized='table') }}

with items as (
    select * from {{ source('stripe', 'invoice_line_items') }}
),
rates as (
    select currency, rate_date, rate_to_base from {{ ref('currency_rates') }}
),
-- month spine covering the full span of all line items; generate_series over dates is
-- Postgres/DuckDB syntax — swap in your warehouse's month generator if it differs.
month_spine as (
    select generate_series(
        date_trunc('month', min(period_start)),
        date_trunc('month', max(coalesce(period_end, period_start))),
        interval '1 month'
    ) as month
    from items
),
recognized as (
    select
        i.id,
        i.subscription_id,
        i.customer_id,
        i.product_id,
        i.period_start::date as period_start,
        i.period_end::date   as period_end,
        i.currency,
        i.amount             as line_amount,
        (i.subscription_id is not null) as is_recurring,
        s.month::date        as month,
        -- number of service months, to split the line amount evenly across the period
        count(*) over (partition by i.id) as service_months
    from items i
    join month_spine s
        on s.month >= date_trunc('month', i.period_start)
       and s.month <= date_trunc('month', case
               when i.subscription_id is not null then coalesce(i.period_end, i.period_start)
               else i.period_start
           end)
)
select
    r.id                               as revenue_item_id,
    r.month,
    r.subscription_id,
    r.customer_id,
    r.product_id,
    r.period_start,
    r.period_end,
    r.is_recurring,
    r.currency                         as original_currency,
    r.line_amount / r.service_months   as original_amount,
    -- base-currency amount at the month's rate. A MISSING rate stays NULL on purpose so the
    -- not_null test on `amount` fails loudly instead of silently assuming 1:1 parity. Seed the
    -- base currency itself at rate_to_base = 1.0 so base-currency rows resolve.
    (r.line_amount / r.service_months) * rt.rate_to_base as amount
from recognized r
left join rates rt
    on rt.currency = r.currency
   and rt.rate_date = r.month
