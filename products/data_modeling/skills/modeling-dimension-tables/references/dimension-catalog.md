# Common dimensions catalog

For each dimension: how to source it, its natural key, and notes. Model each as one row per key.

| Dimension              | Natural key                             | Source it by                                                                   | Notes                                                                                        |
| ---------------------- | --------------------------------------- | ------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------- |
| **Country**            | `country_code` (ISO-2)                  | Derive from `properties.$geoip_country_code` on events, or upload an ISO list. | Enrich with region/continent from an uploaded lookup.                                        |
| **Region / continent** | `country_code` → `region`               | Upload a country→region CSV (seed / warehouse source).                         | Conforms with the country dimension; join on `country_code`.                                 |
| **Timezone**           | `timezone` (IANA, e.g. `Europe/Berlin`) | From `properties.$timezone`, or a country→timezone lookup (upload).            | One country can have many timezones; key on the IANA string, not the country.                |
| **Currency**           | `currency` (ISO-4217)                   | **Built in** — use `convertCurrency()`; no table needed on PostHog.            | Only build a `dim_currency_rate` in dbt (no equivalent there) or for a non-default provider. |
| **Date**               | `date`                                  | Generate a calendar spine (date, week, month, quarter, DOW, is_weekend).       | Classic conformed dimension; cheap; materialize once.                                        |
| **Plan / tier**        | `plan_id` or `plan_name`                | Upload a plan→tier→price lookup, or sync from Stripe products.                 | Join to revenue facts for tier-level revenue.                                                |
| **Product**            | `product_id`                            | Managed `revenue_analytics` product view, or sync from source.                 | Prefer the managed view if it exists (see `modeling-revenue-metrics`).                       |

## Sourcing patterns

- **Upload / seed** — small, hand-maintained lookups (country→region, plan→tier). On PostHog: upload a CSV
  as a warehouse source. In dbt: a `seeds/*.csv` + `dbt seed`.
- **Warehouse source** — dimensions owned by a system of record (Stripe products, your app's `plans` table).
  Connect via `setting-up-a-data-warehouse-source`, then shape the raw table into a clean aliased view.
- **Derive from events** — dimensions implied by captured data (countries actually seen, plans observed).
  `SELECT DISTINCT` + `argMax` to pick the latest value per key. Cheapest, but only covers values that appear
  in events.

## Keys and grain

The natural key must be truly unique in the dimension — dedupe before saving. If a raw source has multiple
rows per key (history, per-source duplicates), collapse to one row (`argMax` by updated-at) or model an
explicit slowly-changing dimension. Fact tables carry the key; the dimension carries everything else.
