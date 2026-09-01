-- Gross revenue (recurring + one-time, net of refunds) per month, split by recurring vs one-time.
-- Replace <revenue_item_view> with the discovered managed view name (see mrr_and_arr.sql).
SELECT
    toStartOfMonth(timestamp)                       AS month,
    sum(amount)                                     AS gross_revenue,
    sumIf(amount, is_recurring)                     AS recurring_revenue,
    sumIf(amount, NOT is_recurring)                 AS one_time_revenue,
    sumIf(amount, amount < 0)                       AS refunds
FROM <revenue_item_view>
GROUP BY month
ORDER BY month
