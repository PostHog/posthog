-- Monthly Recurring Revenue (and ARR) over time, from the managed revenue_item view.
-- The managed `mrr` view is only a live snapshot, so derive the time series from recurring revenue_item rows.
--
-- Before creating the view, replace <revenue_item_view> with the real name for your project:
--   SELECT table_name FROM system.information_schema.tables WHERE table_name ILIKE '%revenue_item%';
-- e.g. `revenue_analytics.all.revenue_item_revenue_view` (cross-source) or `stripe.<prefix>.…`.
--
-- `amount` is already in the project base currency. Every output column is aliased (required by view-create).
SELECT
    toStartOfMonth(timestamp)            AS month,
    sum(amount)                          AS mrr,          -- recognized recurring revenue this month
    sum(amount) * 12                     AS arr_run_rate, -- MRR x 12
    count(DISTINCT customer_id)          AS paying_customers,
    round(sum(amount) / nullif(count(DISTINCT customer_id), 0), 2) AS arpa -- avg revenue per account
FROM <revenue_item_view>
WHERE is_recurring
GROUP BY month
ORDER BY month
