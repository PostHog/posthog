-- Conformed date dimension: one row per calendar day with common attributes.
-- Uses dbt_utils.date_spine; adjust the range and your warehouse's date functions as needed.
{{ config(materialized='table') }}

with spine as (
    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('2020-01-01' as date)",
        end_date="cast('2031-01-01' as date)"
    ) }}
)
select
    date_day::date                          as date,
    extract(year   from date_day)           as year,
    extract(month  from date_day)           as month,
    extract(day    from date_day)           as day_of_month,
    date_trunc('week',  date_day)::date      as week_start,
    date_trunc('month', date_day)::date      as month_start,
    extract(quarter from date_day)          as quarter,
    extract(dow from date_day)              as day_of_week,
    extract(dow from date_day) in (0, 6)    as is_weekend
from spine
