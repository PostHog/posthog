---
name: modeling-dimension-tables
description: >
  Build reusable dimension / lookup tables for a star schema — country/region, timezone, currency, date,
  plan/product, and other descriptive attributes — on either PostHog data-warehouse views (HogQL) or an
  external dbt project. Use when the user wants to model dimension tables, lookup tables, a star schema,
  conformed dimensions, or wants to enrich events/revenue/usage with country, region, timezone, plan, or
  currency attributes without repeating JOINs. Covers sourcing the dimension data (upload, warehouse source,
  or derive from events), shaping it into an aliased one-row-per-entity view (optionally materialized on a
  slow schedule since dimensions change rarely), and attaching it to facts via a saved or person join so its
  columns read as native fields. Key rule: for currency use the built-in convertCurrency() instead of a
  hand-rolled rate table. Read modeling-warehouse-foundations first; dimensions here are reused by the
  revenue, conversion, activation, and product-usage modeling skills.
---

# Modeling dimension tables (star schema)

Dimensions are the descriptive tables (`dim_country`, `dim_plan`, `dim_date`) that fact tables join to for
slicing. This skill builds them once, cleanly, so every other model reuses them instead of re-deriving
lookups. Read `modeling-warehouse-foundations` first (joins + `convertCurrency()` live there). Catalog of
common dimensions: [`references/dimension-catalog.md`](references/dimension-catalog.md); recipes in
[`references/posthog/`](references/posthog/) and [`references/dbt/`](references/dbt/).

## Star schema in one screen

**Facts** (events, charges, revenue items) are long, keyed, and additive. **Dimensions** are short, one row
per entity, descriptive. You model a dimension in three moves:

1. **Source it** — where does the dimension data come from?
   - _Upload / seed_ a lookup (country→region, plan→tier) as a CSV (warehouse source or dbt seed).
   - _Sync_ it from a system of record (your app DB, Stripe products) as a warehouse source.
   - _Derive_ it from events (distinct countries seen, a plan property observed per person).
2. **Shape it** — an **aliased** `SELECT` with clean column names, **one row per entity** (dedupe hard).
   Save as a view; **materialize** it on a **slow** `sync_frequency` (`7day`/`30day`) since dimensions change
   rarely and are read constantly.
3. **Attach it** — a **saved join** (dimension → a fact table) or **person join** (dimension → persons) so
   its columns appear as native fields in any query, filter, or breakdown. See foundations
   `joins-and-dimensions.md`.

## Currency is already a managed dimension — don't build it

PostHog ships exchange rates behind `convertCurrency(from, to, amount, timestamp?)` (Open Exchange Rates,
historical-rate-correct). Use it directly for any money conversion. Only build a currency dimension yourself
in **dbt** (which has no equivalent), or if you need a rate provider PostHog doesn't offer.

## Rules before you model

1. **One row per entity, unique key.** A dimension with duplicate keys silently fan-outs every fact it joins.
   Test uniqueness (PostHog: verify in the shaping query; dbt: `unique` + `not_null`).
2. **Alias to clean, stable names** — `country_code`, `region`, `plan_tier`. These names become the join
   surface everything else depends on.
3. **Materialize static dimensions on a slow schedule**; don't leave a constantly-read lookup virtual.
4. **Register and certify.** Annotate the dimension and, if it's load-bearing, certify it in the catalog
   (foundations `governance.md`) so other models discover it and don't build a rival copy.
5. **Prefer built-in currency** (`convertCurrency`) over a hand-rolled FX table on PostHog.

## Build it

**PostHog:** shape an aliased dimension view, then materialize + join. Recipes:
[`references/posthog/dim_country.sql`](references/posthog/dim_country.sql) (derive + enrich from events),
[`dim_plan.sql`](references/posthog/dim_plan.sql) (lookup/upload pattern).

**dbt:** conformed `dim_*` models with `unique`/`not_null`/`relationships` tests, plus a generated
`dim_date`. Recipes: [`references/dbt/`](references/dbt/).

## File map

| File                                                                 | Read when                                                   |
| -------------------------------------------------------------------- | ----------------------------------------------------------- |
| [`references/dimension-catalog.md`](references/dimension-catalog.md) | Common dimensions, how to source each, and the natural key. |
| [`references/posthog/`](references/posthog/)                         | HogQL aliased-dimension view recipes.                       |
| [`references/dbt/`](references/dbt/)                                 | dbt `dim_date` / `dim_country` + `schema.yml` tests.        |

## Companions

`modeling-warehouse-foundations` (joins + currency), `setting-up-a-data-warehouse-source` /
`suggesting-data-imports` (sync/upload the source data), and the models that consume these dimensions:
`modeling-revenue-metrics`, `modeling-conversion-metrics`, `modeling-activation-metrics`,
`modeling-product-usage-metrics`.
