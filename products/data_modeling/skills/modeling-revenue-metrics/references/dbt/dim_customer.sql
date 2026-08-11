-- Customer dimension, one row per customer. Analogue of PostHog's managed customer view.
{{ config(materialized='table') }}

select
    id            as customer_id,
    name          as customer_name,
    email,
    address_country as country,
    created::date as first_seen_date
from {{ source('stripe', 'customers') }}
