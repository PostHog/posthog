# dbt / external-warehouse modeling

## The honest picture — read this first

**PostHog has no native dbt integration.** There is no connector that runs dbt for you, and PostHog's own
warehouse models are HogQL views, not dbt models. So "the dbt path" always means **dbt runs externally**, in
the user's own environment, against a warehouse — not inside PostHog. Two realistic topologies:

1. **PostHog is a source, your warehouse is the modeling layer.** You already have (or set up) a warehouse
   (Snowflake / BigQuery / Postgres / DuckDB / …). PostHog event/person data reaches it via a batch export or
   your own pipeline; other business data lands there too. dbt models it. PostHog can then read the _results_
   back by connecting your warehouse as a **data-warehouse source** (see `setting-up-a-data-warehouse-source`)
   so the modeled tables show up alongside events.
2. **PostHog's managed warehouse (beta, waitlist).** PostHog offers a managed DuckDB-backed warehouse that
   gives you direct credentials, so you can point dbt (and other BI tools) straight at it. This is the
   forward-looking home for external modeling, but it is **beta / waitlist-gated** — confirm the user has
   access before assuming it. It is not the integrated warehouse behind the `view-*` tools.

If the user isn't already invested in dbt and their data is in PostHog, the **PostHog-native view path is
simpler** — no external warehouse, scheduler, or CI to run. Recommend dbt when they already run it, need
multi-model lineage with tests in CI, or are modeling data that lives outside PostHog.

## Project layout

Standard three layers. The copy-paste starting point is [`dbt-skeleton/`](dbt-skeleton/).

```text
your_dbt_project/
  dbt_project.yml
  models/
    staging/          # 1:1 with sources, light cleaning/renaming, materialized as views
      _sources.yml    # declares the raw tables (PostHog export, Stripe, your DB)
      stg_events.sql
    marts/            # business logic — the actual metric; materialized as tables
      schema.yml      # tests + docs for the marts
      fct_<metric>.sql
      dim_<entity>.sql
```

- **staging** — one model per source table, `materialized: view`, only renames/casts/filters. No joins, no
  business logic. Names `stg_<source>__<entity>`.
- **marts** — the metric or dimension, `materialized: table` (or incremental for large fact tables). Fact
  tables `fct_*`, dimensions `dim_*`. This is where a domain skill's business logic lives.
- **tests** — in `schema.yml`: `unique` + `not_null` on keys, `accepted_values` on enums,
  `relationships` from facts to dimensions. Ship tests with every mart; they are the dbt equivalent of the
  aliasing/validation discipline the PostHog path gets for free.

## Mapping to the PostHog path

A domain skill ships both. The metric definition is identical; only the substrate differs:

| PostHog-native                          | dbt                                                                  |
| --------------------------------------- | -------------------------------------------------------------------- |
| staging view (virtual)                  | `staging/stg_*.sql` (`materialized: view`)                           |
| metric view, materialized               | `marts/fct_*.sql` (`materialized: table`)                            |
| `sync_frequency`                        | your dbt scheduler / CI cadence (`dbt build` on cron)                |
| column annotations                      | `schema.yml` descriptions                                            |
| aliasing rule enforced by `view-create` | `unique`/`not_null` tests in `schema.yml`                            |
| `convertCurrency()` (built in)          | you must supply an exchange-rate seed/source — dbt has no equivalent |

Currency is the one place the stacks genuinely diverge: PostHog gives you `convertCurrency()` for free; in
dbt you provide your own rate table (a dbt seed or a synced source) and join to it. Call this out whenever a
model needs multi-currency normalization.

## Running it

`dbt build` (runs models + tests) on whatever schedule the team uses — locally, in CI, or via a scheduler.
A full run needs live warehouse credentials, so the skeleton in this repo is **structure you verify by
compiling** (`dbt parse` / `dbt compile`), not something this skill can execute end-to-end for the user.
