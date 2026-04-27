---
name: layering-warehouse-models
description: >
  Conventions for organizing PostHog data warehouse models into conceptual
  layers — raw / staging / intermediate / final. Use before creating any new
  `DataWarehouseSavedQuery`, when reviewing an existing modeling project that's
  grown organically, when a user asks "where  should this view live?" or "what
  should I call this?", or when deciding whether to split a tangled view into
  multiple  models. Pure methodology — works alongside `modeling-lifecycle`
  (which uses these conventions) without requiring any new tools.
---

# Layering warehouse models

A useful data warehouse looks like a pipeline, not a pile. Each model has one job and a single layer. Each layer
makes the next one cheaper to write and cheaper to trust. Without conventions, every model becomes a one-off and
the warehouse rots — duplicated logic, ambiguous names, joins that return wrong numbers because two "revenue"
views compute it differently.

This skill is the convention. Apply it whenever a model is being created, renamed, or refactored.

## When to use this skill

- Before calling `view-create` for any new model — pick the right layer and name first
- The user is starting a modeling project from scratch and asks how to structure it
- An existing project has views named ad-hoc (`final_revenue_v2`, `clean_users_TEMP`) and the user wants to clean up
- A view is doing too many things at once and needs to be split
- Two models compute "the same number" two different ways and the team is arguing about which is right

This is a methodology skill — there are no MCP tools to call here. Use it as a reference while the
`modeling-lifecycle` skill drives the work.

## The four layers

```text
   ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
   │   raw   │ →  │   stg   │ →  │   int   │ →  │  final  │
   │ source  │    │  clean  │    │ joined  │    │ shaped  │
   │ tables  │    │ + typed │    │ + grain │    │ for use │
   └─────────┘    └─────────┘    └─────────┘    └─────────┘
        ↑              ↑              ↑              ↑
   from sync       from raw       from stg       from int
                                                    (or stg)
```

Each arrow is "depends on". The graph flows in one direction — staging never reads from a final, intermediate never
reads from another intermediate's downstream. Cycles are a smell.

### "raw" — what the source gave us

The synced source tables themselves. In PostHog you usually don't author these — they're produced by the warehouse
sync (e.g. `stripe_charges`, `postgres_prod_orders`). Native PostHog tables (`events`, `persons`, `sessions`,
`groups`) are also raw.

Treat raw as read-only and quirky:

- Column names are whatever the source picked (`updatedAt`, `created_at`, `inserted_dt`).
- Types are whatever the source declared, often `String` for things that should be `DateTime` or `Decimal`.
- Status values are inconsistent (`active`, `Active`, `ACTIVE` in the same column).
- Nulls are everywhere.

Hence, you should never have to name a model `raw_*`. If you find yourself referencing a synced source table directly from a
`int_*` or `final_*` view, that's a sign you're missing a staging layer.

### `stg_*` — one cleaned model per source entity

One staging model per source-and-entity. `stg_stripe__invoices`, `stg_stripe__customers`,
`stg_postgres_prod__orders`, `stg_hubspot__contacts`. Each one:

- Renames source columns to consistent casing and snake_case.
- Casts types so downstream models can trust them (`toDateTime(created_at_str) AS created_at`).
- Normalizes enums (`lower(status) AS status`).
- Drops columns the rest of the warehouse will never need.
- Adds simple derived columns that are obviously per-row (e.g. `amount / 100.0 AS amount_dollars` for Stripe's
  cents-stored amounts).

Staging does **not** join. Staging does **not** aggregate. One row in, one row out (after filters). If you find
yourself wanting to join in a staging model, what you actually want is an `int_*` model that depends on two
staging models.

Typically one `stg_*` per "raw" source. If two staging models cover the same source entity, you have drift waiting
to happen.

### `int_*` — joined and re-grained

Intermediate models combine staging models, change grain, or compute reusable derived facts that more than one
final model would want. Examples:

- `int_subscription_daily` — one row per (subscription, day) by exploding `stg_stripe__subscriptions` over its
  active period.
- `int_customer_with_first_order` — `stg_stripe__customers` joined to the earliest `stg_stripe__charges`.
- `int_account_revenue` — joins of charges + refunds + credits, ready to be aggregated by any final model.

Intermediate models can be expensive (they often join), so this is the layer where you most often consider
materializing — but only when the same intermediate is reused by multiple final models. A one-off intermediate that
only feeds a single final model is usually better inlined into that final model, or kept virtual.

### `final_*` — the thing the user actually queries

The shape that lands in a dashboard, an insight, a Slack alert, or a CSV export. One final model per business question:
`final_mrr`, `final_active_accounts`, `final_weekly_signups`, `final_funnel_signup_to_paid`.

Final models are where aggregates and finalized filters live. If a final model is doing complex joins of raw tables, push that
work back into intermediate models — final models should look mostly like aggregations on top of well-shaped inputs.

Final models are the layer that should usually be materialized (see `modeling-lifecycle` for the materialization
defaults). Sometimes it is also worth materializing intermediate models.

## Naming

Use lowercase, underscore-separated. The convention is:

| Layer        | Pattern                        | Example                                                  |
| ------------ | ------------------------------ | -------------------------------------------------------- |
| Raw          | `<source_prefix>_<table_name>` | `stripe_charges` (set by sync; no need for custom names) |
| Staging      | `stg_<source>__<entity>`       | `stg_stripe__invoices`                                   |
| Intermediate | `int_<grain_or_concept>`       | `int_subscription_daily`                                 |
| Final        | `final_<domain_or_metric>`     | `final_mrr`                                              |

Notes on the patterns:

- **Double underscore in `stg_<source>__<entity>`** is a deliberate visual separator between the source and the
  entity. `stg_stripe_invoices` is ambiguous if the source name has an underscore (`stg_postgres_prod_orders` —
  is the source `postgres` and the table `prod_orders`, or source `postgres_prod` and table `orders`?). The `__`
  removes that ambiguity (`stg_postgres_prod__orders`).
- **Final models don't need a source.** They're domain-named. `final_mrr` is unambiguous; `final_stripe_mrr` is wrong if
  the final model actually pulls from multiple sources (Stripe + Hubspot for plan metadata, say).
- **Avoid version suffixes (`_v2`, `_new`, `_final`).** They always survive the rewrite and become permanent
  confusion. If you need to replace a model, replace it in place — `view-update` exists for this. Use a draft
  workflow if you need to compare versions.
- **No personal names.** `andrews_mrr_view` is a debt the next data analyst/engineer inherits.

## One job per model

A model that does many things at once is hard to understand, hard to test, and hard to compose into other
models. The layer system encodes this as a checklist:

- A `stg_*` does cleaning. If it joins or aggregates, split it.
- An `int_*` does joining or re-graining. If it has dashboard-ready filters / KPIs, push those into a `final_*`.
- A `final_*` does final shaping for consumption. If it's reading raw tables directly or doing big joins, push
  that work into intermediate or staging model.

When in doubt, **split**. Two simple models are easier to fix than one complex one. The cost of an extra view is
~zero if it's not materialized; the cost of a tangled view that quietly returns wrong numbers is high.

## When to split a model

Concrete signals that a single model should become two:

- **Multiple grains in the output.** If your model has both `customer_id` rows and `(customer_id, day)` rows, you
  have two models pretending to be one.
- **The SQL is more than one CTE deep _and_ the CTEs do meaningfully different jobs** (cleaning + joining +
  aggregating). The CTEs are telling you the layer boundaries — promote them to real models.
- **Two consumers want slightly different filters.** Build a single intermediate without filters and let each
  final model apply its own.
- **A change in the SQL silently breaks a downstream metric.** That's a sign the model is doing too much for any
  one consumer to fully reason about.

## When not to split

Don't manufacture layers for the sake of conformity:

- **A small, single-source final model with no reusable intermediate.** It's fine for a `final_*` to read directly from
  `stg_*` — not every final model needs an `int_*` underneath.
- **A `stg_*` that's nearly identical to the raw table.** If a source already has clean columns and consistent
  types (well-managed Postgres tables, for instance), the staging model is just `SELECT * FROM postgres`. That's
  still worth keeping — it's the contract — but don't try to add fake transformations.
- **One-off exploratory queries.** Save them as views for reuse, but don't pretend they're part of the layered
  warehouse. Drop them into a separate folder or unprefix them. The layer prefixes are a promise about the
  graph; keep them load-bearing.

## A short worked example

User asks for "MRR by account by month, joined with the AE who owns the account."

A bad single-model attempt:

```sql
-- final_mrr_by_ae
SELECT toMonth(c.created) AS month, h.owner_email, sum(c.amount) / 100 AS mrr
FROM stripe_charges c
JOIN hubspot_companies h ON c.customer_email = h.email
WHERE c.status = 'succeeded' AND c.amount > 0 AND lower(c.refunded) = 'false'
GROUP BY 1, 2
```

Problems: reads raw tables, hard-codes Stripe enum cleanup, joins on a key that hasn't been validated, mixes
cleaning + joining + aggregating in one breath. Rebuilds the same joins for every other revenue final model.

A layered version:

| Model                       | Job                                                           |
| --------------------------- | ------------------------------------------------------------- |
| `stg_stripe__charges`       | Clean status, cast amount to dollars, filter refunds          |
| `stg_hubspot__companies`    | Normalize email casing, drop unused fields                    |
| `int_account_revenue_daily` | Join cleaned charges to companies, one row per (account, day) |
| `final_mrr_by_ae`           | Aggregate `int_account_revenue_daily` by month + AE           |

Now `final_arr_by_segment`, `final_revenue_by_plan`, etc. all can reuse `int_account_revenue_daily` and don't have to
re-derive "what counts as revenue" — that lives in one place.

## Important notes

- **The layers are a promise about the dependency graph.** A `final_*` that depends on a raw table breaks the
  promise; a `stg_*` that depends on another `stg_*` breaks the promise. Keep the arrows pointing forward.
- **One source entity → one staging model.** Multiple staging models for the same source table are how the
  warehouse splits into incompatible versions of "the truth".
- **No version suffixes.** Edit in place; use the draft workflow if you need a side-by-side comparison.
- **Layers, then materialization.** First put the model in the right layer with the right name; _then_ decide
  whether to materialize. Materializing a misplaced model just makes the wrong shape faster.
- **Splits are cheap when virtual.** A `view-create` of a tiny staging model costs nothing if it isn't
  materialized. Don't keep a tangled model "to save a view" — that's a false economy.
- **This skill pairs with `modeling-lifecycle`.** That skill drives the build; this skill picks the names and
  layers as you go.
