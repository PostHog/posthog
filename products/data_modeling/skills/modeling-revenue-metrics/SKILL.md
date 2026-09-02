---
name: modeling-revenue-metrics
description: >
  Build reusable revenue models — MRR, ARR, gross revenue, new/expansion/contraction/churn, ARPU, LTV, and
  per-customer/per-account revenue — on either PostHog data-warehouse views (HogQL) or an external dbt
  project. Use when the user wants to model, define, or compute recurring revenue, monthly/annual recurring
  revenue, churn or retention of revenue, lifetime value, average revenue per user, or revenue by customer,
  cohort, product, or currency. On PostHog, build on the managed revenue_analytics_* views (revenue_item,
  mrr, customer, subscription, charge, product) fed by Stripe or custom revenue events — not raw Stripe
  tables — and normalize money with convertCurrency(). In dbt, stage the payment source and compute
  fct_mrr / fct_revenue_item / dim_customer marts with tests. Covers picking the right source, the
  subscription-config gotcha that leaves MRR empty, currency handling, and linking revenue to persons/groups.
  Read modeling-warehouse-foundations first for the view-vs-dbt mechanics.
---

# Modeling revenue metrics

Turn payment/subscription data into durable revenue models. Read `modeling-warehouse-foundations` first for
the view-vs-dbt decision, the `view-*` workflow, and `convertCurrency()`; this skill is the revenue-specific
layer on top. Metric definitions live in
[`references/revenue-metric-definitions.md`](references/revenue-metric-definitions.md); copy-paste recipes in
[`references/posthog/`](references/posthog/) and [`references/dbt/`](references/dbt/).

## Step 1 — find where revenue lives

Revenue reaches PostHog two ways; both feed the same **managed `revenue_analytics_*` views**:

- **A payment platform as a warehouse source** — Stripe today (Chargebee/Polar/RevenueCat coming). Best when
  the business runs on a billing platform. Connect via `setting-up-a-data-warehouse-source`.
- **Custom revenue events** — you send events (e.g. `purchase_completed`) with a revenue property. Best when
  there's no supported platform or you already track revenue in-product.

If neither exists yet, use `suggesting-data-imports` to recommend a source. In **dbt**, the equivalent is
staging whichever billing tables landed in the warehouse.

## Step 2 — model on the managed views, not raw tables

PostHog auto-generates a curated set of views per source. **Do not re-derive revenue from raw Stripe
tables** — the managed views already handle deferred-revenue recognition, currency, and a stable schema.

Discover the exact names (they're prefixed by source, e.g. `stripe.<prefix>.…`, plus a cross-source
`revenue_analytics.all.…`):

```sql
SELECT table_name FROM system.information_schema.tables WHERE table_name ILIKE '%revenue_analytics%'
```

| Managed view                    | Grain                        | Use for                                                                                                               |
| ------------------------------- | ---------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `revenue_item` (**start here**) | 1 / invoice line item        | Gross revenue, monthly recurring revenue, revenue by product/customer/period. Implements deferred revenue + currency. |
| `mrr`                           | 1 / (customer, subscription) | **Live snapshot** of current MRR — not a time series.                                                                 |
| `customer`                      | 1 / customer                 | `dim_customer`: email, country, cohort, metadata.                                                                     |
| `subscription`                  | 1 / subscription             | Subscription state for churn/expansion logic.                                                                         |
| `charge`                        | 1 / charge                   | Raw charges; prefer `revenue_item` unless you specifically need charges.                                              |
| `product`                       | 1 / product                  | Product dimension.                                                                                                    |

Key `revenue_item` columns: `amount` (already converted to the project **base currency**), `currency` (that
base currency), `original_amount` / `original_currency` (as charged), `is_recurring`, `customer_id`,
`subscription_id`, `product_id`, `group_0_key`…`group_4_key` (B2B account keys), `timestamp`.

## Rules before you model (revenue gotchas)

1. **MRR is empty without a subscription config.** For event-based revenue, MRR only populates when a
   subscription property is configured. Empty MRR + populated gross revenue is **expected behaviour**, not a
   bug — say so instead of "fixing" it.
2. **The `mrr` managed view is a current snapshot**, not history ("MRR at the current time"). For MRR _over
   time_, sum recurring `amount` per month from `revenue_item` (see the recipe), or materialize a monthly
   snapshot of the `mrr` view on a schedule.
3. **`amount` is already in base currency.** Use it directly for reporting. Only call
   `convertCurrency(original_currency, 'XXX', original_amount, timestamp)` when you need a _different_ target
   currency, or when working from raw events.
4. **Link revenue to people via metadata.** Person/group-level revenue needs
   `posthog_person_distinct_id` metadata on the Stripe customer (or the person join). Without it, revenue is
   customer-level only.
5. **Don't build on the Revenue dashboard** — it's being retired (~2026-06-30). Model against the
   `revenue_analytics_*` views and the person/group revenue properties.
6. **Exclude test accounts.** Confirm `filter_test_accounts` behaviour so QA/internal charges don't inflate
   revenue.

## Step 3 — build the model

**PostHog:** write the HogQL (alias every column), `view-create`, verify with `view-get`, then
`view-materialize` the expensive monthly rollups (a daily `sync_frequency` is usually right for revenue).
Recipes: [`references/posthog/`](references/posthog/) — `mrr_and_arr.sql`, `gross_revenue_by_month.sql`,
`revenue_by_customer.sql`.

**dbt:** stage the billing source → `fct_revenue_item`, `fct_mrr`, `dim_customer` marts with tests.
Recipes: [`references/dbt/`](references/dbt/). Note dbt has no `convertCurrency()` — supply a rate seed.

Then register the model (`references/governance.md` in foundations): annotate columns and, if MRR/ARR is a
headline number, propose it to the semantic layer.

## File map

| File                                                                                   | Read when                                                                         |
| -------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| [`references/revenue-metric-definitions.md`](references/revenue-metric-definitions.md) | Precise definitions: MRR, ARR, gross, new/expansion/contraction/churn, ARPU, LTV. |
| [`references/posthog/`](references/posthog/)                                           | HogQL view recipes on the managed views.                                          |
| [`references/dbt/`](references/dbt/)                                                   | dbt staging + `fct_*`/`dim_*` marts + `schema.yml` tests.                         |

## Companions

`modeling-warehouse-foundations` (mechanics), `setting-up-a-data-warehouse-source` +
`suggesting-data-imports` (get Stripe/revenue data in), `modeling-dimension-tables` (currency/plan
dimensions), `querying-posthog-data` (HogQL + the semantic-layer metric check).
