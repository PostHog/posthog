# Joins, dimensions & currency

How to attach dimension/lookup data to fact data on each stack. The full star-schema treatment (building the
dimensions themselves) is the `modeling-dimension-tables` skill; this is the shared mechanics.

## PostHog: three ways to join

1. **Saved table join** (persistent). Define once (SQL editor → source table → _Add join_), specifying
   `source_table.key = joined_table.key`. After that the joined table's columns are addressable as nested
   fields on the source table in _any_ query, filter, or breakdown — e.g. after joining
   `events.distinct_id → stripe_customer.email`, you can `SELECT stripe_customer.plan FROM events`. This is
   the built-in way to hang a dimension off a fact stream without repeating JOIN syntax.
2. **Person join** (persistent, special case). Join a warehouse/dimension table onto `persons` so its columns
   behave like native person properties across insights, filters, breakdowns, and cohorts — not just one
   query. Use for customer/account dimensions you want available product-wide.
3. **Ad-hoc HogQL join** (one-off). Plain `JOIN` / `LEFT JOIN` in a query or view for a single analysis, no
   persistence. Fine inside a view's HogQL when the join is specific to that model.

Prefer a **saved or person join** for a dimension many models reuse; use an ad-hoc join for logic local to
one view. When you don't know the join key, check `system.information_schema.relationships` for an accepted
join before guessing (see `governance.md`).

## dbt: joins live in marts

In dbt you `JOIN` staging models inside a `marts/` model and assert the relationship with a `relationships`
test in `schema.yml` (fact row's FK exists in the dimension). There's no "saved join" concept — the join is
just SQL, and the test guarantees referential integrity.

## Currency

PostHog ships a managed exchange-rate dimension so you don't build one:

```sql
convertCurrency(from_currency, to_currency, amount, timestamp?)
-- e.g. normalize each charge to USD at its historical rate:
SELECT convertCurrency(currency, 'USD', amount, timestamp) AS amount_usd FROM ...
```

Rates come from Open Exchange Rates, stored at daily granularity, applied at the historical rate as of the
`timestamp` (omit it for the latest rate). Use this for any multi-currency revenue model instead of a
hand-rolled rate table. It is not configurable to another rate provider.

In **dbt** there is no equivalent — supply your own rate table (a dbt seed CSV, or a synced source) keyed by
`(currency, date)` and join to it in the mart. This is the main place the two stacks diverge.

## Star schema in one line

Facts (`events`, charges, revenue items) carry foreign keys; dimensions (`dim_country`, `dim_plan`,
`dim_currency`) carry descriptive attributes. On PostHog, dimensions are aliased (often materialized) views
attached via saved/person joins; in dbt they are `dim_*` marts joined in `fct_*` models. Keep dimension
grain at one row per entity and test the key is `unique`.
