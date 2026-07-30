-- All-time revenue per customer, enriched with the customer dimension (name, country, cohort).
-- Demonstrates joining a managed fact view to the managed customer view, and a currency conversion
-- to a chosen reporting currency (here EUR) from the ORIGINAL amount as charged.
--
-- Replace the two managed view names with the discovered ones:
--   SELECT table_name FROM system.information_schema.tables WHERE table_name ILIKE '%revenue_analytics%';
SELECT
    c.id                                                          AS customer_id,
    any(c.name)                                                   AS customer_name,
    any(c.country)                                                AS country,
    sum(ri.amount)                                                AS revenue_base_ccy,
    sum(convertCurrency(ri.original_currency, 'EUR', ri.original_amount, ri.timestamp)) AS revenue_eur,
    count(DISTINCT ri.subscription_id)                            AS subscriptions
FROM <revenue_item_view> AS ri
LEFT JOIN <customer_view> AS c ON ri.customer_id = c.id
GROUP BY customer_id
ORDER BY revenue_base_ccy DESC
