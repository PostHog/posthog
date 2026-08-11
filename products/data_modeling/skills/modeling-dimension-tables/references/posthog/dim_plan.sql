-- Plan dimension from an uploaded/synced plan lookup, deduped to one row per plan_id.
-- Pattern for any hand-maintained or system-of-record lookup: alias to clean names, collapse to one row/key.
-- Replace <plan_source> with the uploaded CSV table or synced source table.
SELECT
    plan_id                                        AS plan_id,
    argMax(plan_name, updated_at)                  AS plan_name,   -- latest value wins if history exists
    argMax(tier, updated_at)                       AS tier,
    argMax(monthly_price, updated_at)              AS monthly_price
FROM <plan_source>
GROUP BY plan_id
-- Attach with a saved join: revenue_item.product_id / subscription plan_id = dim_plan.plan_id,
-- so tier and price read as native fields on the revenue facts.
