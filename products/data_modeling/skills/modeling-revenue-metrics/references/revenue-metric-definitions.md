# Revenue metric definitions

Canonical definitions so every model computes the same number. Amounts assume the project **base currency**
(the `amount` column on `revenue_item` is already converted; see `convertCurrency()` in foundations for other
targets).

| Metric                              | Definition                                                                                  | Notes                                                                                                                                                                                                                                                 |
| ----------------------------------- | ------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Gross revenue**                   | Sum of all revenue in a period, recurring + one-time, including negative amounts (refunds). | `sum(amount)` over `revenue_item` in the period.                                                                                                                                                                                                      |
| **MRR** (Monthly Recurring Revenue) | Normalized recurring subscription revenue for a month.                                      | Recognized recurring revenue per month = `sum(amount) where is_recurring` grouped by month on `revenue_item` (deferred revenue already spreads annual plans across their service period). The managed `mrr` view is a **live snapshot**, not history. |
| **ARR**                             | `MRR × 12`.                                                                                 | A run-rate projection, not a forecast.                                                                                                                                                                                                                |
| **New MRR**                         | MRR from customers who had no MRR in the prior period.                                      |                                                                                                                                                                                                                                                       |
| **Expansion MRR**                   | Increase in MRR from existing customers (upgrade/seat add).                                 |                                                                                                                                                                                                                                                       |
| **Contraction MRR**                 | Decrease in MRR from existing customers still paying.                                       |                                                                                                                                                                                                                                                       |
| **Churned MRR**                     | MRR lost from customers who cancelled or dropped to $0.                                     | New − Contraction − Churn + Expansion reconciles the month-over-month MRR bridge.                                                                                                                                                                     |
| **Churn rate**                      | `churned_customers / total_customers` in the period.                                        | Revenue churn uses churned MRR / starting MRR.                                                                                                                                                                                                        |
| **ARPU**                            | Average revenue per user in a period = `total_revenue / active_users`.                      | Across all revenue, not subscription-only.                                                                                                                                                                                                            |
| **LTV**                             | `ARPU / churn_rate`.                                                                        | Null when churn rate is 0; 0 when there's churn but no revenue.                                                                                                                                                                                       |

## The MRR movement bridge

New / Expansion / Contraction / Churn decompose the change in MRR between two months. Compute per customer:

- prior-month recurring MRR `m0`, current-month recurring MRR `m1`.
- `m0 = 0, m1 > 0` → **New** `m1`.
- `m0 > 0, m1 > m0` → **Expansion** `m1 - m0`.
- `0 < m1 < m0` → **Contraction** `m0 - m1`.
- `m0 > 0, m1 = 0` → **Churn** `-m0`.

`starting_MRR + new + expansion - contraction - churn = ending_MRR`. Use this identity as a validation
check on any MRR model.

## Aggregation unit

Choose person vs group (B2C vs B2B) once. For account-level revenue use `group_0_key` (or the relevant
`group_N_key`) on `revenue_item`; for user-level use `customer_id` joined to persons via the customer
metadata link. Keep it consistent across MRR, churn, and LTV.
