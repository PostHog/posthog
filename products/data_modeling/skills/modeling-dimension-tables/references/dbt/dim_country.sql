-- Country dimension in dbt: a country->region seed joined onto countries observed in staged events.
-- Provide seeds/country_region.csv with columns: country_code, region, continent.
{{ config(materialized='table') }}

with seen as (
    select distinct upper(current_country) as country_code
    from {{ ref('stg_events') }}
    where current_country is not null
),
lookup as (
    select country_code, region, continent from {{ ref('country_region') }}
)
select
    s.country_code,
    l.region,
    l.continent
from seen s
left join lookup l using (country_code)
