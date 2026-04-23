# Billing response shapes

Short reference for what each billing tool returns and how to read the time-series
breakdowns. Field names below are verified against real API responses.

## `billing-list`

Single snapshot of the org's billing state. Key top-level fields:

**Subscription and plan:**

- `has_active_subscription` (bool) - paid vs free plan signal
- `subscription_level` - e.g. `"free"`, `"paid"`, `"custom"`, `"enterprise"`
- `billing_plan` - specific plan identifier string
- `is_annual_plan_customer` (bool)
- `deactivated` (bool)
- `startup_program_label`, `startup_program_label_previous` (often null)
- `free_trial_until` (timestamp or null)
- `account_owner` - who owns the customer record
- `customer_id` - Stripe customer id
- `stripe_portal_url` - URL to Stripe customer portal

**Period and costs:**

- `billing_period.current_period_start`, `billing_period.current_period_end`, `billing_period.interval` (`"month"`, etc.)
- `current_total_amount_usd` - period-to-date cost (note: `current_total_...`, NOT `total_current_...`)
- `current_total_amount_usd_after_discount`
- `projected_total_amount_usd` - forecast for the full period (without spending limits)
- `projected_total_amount_usd_with_limit` - forecast clipped to spending limit
- `projected_total_amount_usd_after_discount`, `projected_total_amount_usd_with_limit_after_discount`
- `discount_amount_usd`, `discount_percent`, `amount_off_expires_at`

**Limits:**

- `custom_limits_usd` - dict keyed by product type (e.g. `{"product_analytics": 100}`). Top-level, NOT per-product.
- `next_period_custom_limits_usd` - same shape
- `never_drop_data` (bool)

**Features:**

- `available_product_features` - array of feature objects with `key`, `name`, `description`, `unit`, `limit`, `note`, `entitlement_only`, `is_plan_default`. **The key is `available_product_features`, not `available_features`.**

**Products:**

- `products` - array of all PostHog products (subscribed OR unsubscribed, with `subscribed` flag). Each has:
  - `name`, `type`, `description`, `headline`, `icon_key`, `image_url`, `screenshot_url`, `docs_url`
  - `subscribed` (bool), `contact_support` (bool), `inclusion_only`, `legacy_product`
  - `current_usage`, `usage_limit`, `percentage_usage`, `has_exceeded_limit`, `projected_usage`
  - `current_amount_usd`, `current_amount_usd_before_addons`, `projected_amount_usd`, `projected_amount_usd_with_limit`, `unit_amount_usd`
  - `unit`, `display_unit`, `display_decimals`, `display_divisor`
  - `free_allocation`, `price_description`, `tiered`, `tiers`, `plans`, `trial`, `usage_key`
  - `features` - feature objects available on this product
  - `addons` - array of addons with a similar shape, plus `included_with_main_product` and `included_if`

**Aggregate usage (for the current period):**

- `usage_summary` - dict keyed by the short usage identifier. Each value is `{usage: int, limit: int|null}`. Keys observed:
  - `events`, `enhanced_persons_events`, `recordings`, `mobile_recordings`
  - `exceptions`, `survey_responses`, `llm_events`, `ai_credits`, `feature_flag_requests`
  - `rows_synced`, `historical_rows_synced`, `rows_exported`, `cdp_trigger_events`
  - `workflow_emails`, `workflow_destinations`, `logs_mb_ingested`
- **Naming mismatch**: `usage_summary` uses short keys like `events`, but the `usage_types` query param on `billing-usage-retrieve` expects the long form like `event_count_in_period`. See `ee.billing.billing_types.UsageType` for the canonical query-param values. The tool's input schema carries the list automatically.
- **`usage_summary` is scoped to the current billing period only.** If the customer's period just rolled over (`billing_period.current_period_start` equals today or is very recent), every usage key will be 0 by design. That is not a bug. For the previous period's story, call `billing-usage-retrieve` with a date range covering the previous period.

**Trial:**

- `trial` - object with `is_active`, `expires_at`, `target`; or `null` if no trial.

Treat `billing-list` as the "who is this customer and what do they pay for" call.

## `billing-usage-retrieve` and `billing-spend-retrieve`

Both return the same envelope:

```json
{
  "status": "ok",
  "customer_id": 135,
  "type": "timeseries",
  "results": [ ... ],
  "team_id_options": [1659, ...]
}
```

- `results` is the array of time-series items.
- `team_id_options` lists team IDs the customer has usage for (useful for mapping team IDs back to project names when the agent doesn't have that context).

### `results[]` item shape (verified)

```json
{
  "id": 5,
  "label": "Hedgebox::Identified Events",
  "dates": ["2026-04-15", "2026-04-16"],
  "data": [11667.0, 0.0],
  "breakdown_type": "multiple",
  "breakdown_value": ["enhanced_persons_event_count_in_period", "1659"]
}
```

- `id` - integer, 0-indexed.
- `label` - human-friendly label.
  - With `breakdowns=["type"]` (or no breakdowns): just the usage type label, e.g. `"Identified Events"`.
  - With `breakdowns=["type","team"]`: `"<ProjectName>::<UsageTypeLabel>"`, e.g. `"Hedgebox::Events"`.
- `dates` - array of YYYY-MM-DD strings.
- `data` - array of **floats** (not ints). Parallel to `dates`.
- `breakdown_type`:
  - Single breakdown: `"type"` or `"team"` (the breakdown name).
  - Multiple breakdowns: the literal string `"multiple"` (NOT the second breakdown name).
  - No breakdowns: defaults to `"type"` (the response looks identical to `breakdowns=["type"]`).
- `breakdown_value`:
  - Single breakdown or no breakdown: a **string**, e.g. `"enhanced_persons_event_count_in_period"`.
  - Multiple breakdowns: an **array**. Order matches the breakdowns request. With `breakdowns=["type","team"]` the shape is `[usage_type_identifier, team_id_as_string]`, e.g. `["event_count_in_period", "1659"]`.

**Practical consequence**: always branch on `isinstance(breakdown_value, list)` before indexing.

**Important**: `breakdowns` must be a JSON-encoded array, not a comma-separated string.
Agents should pass e.g. `breakdowns=["type","team"]`, URL-encoded as
`breakdowns=%5B%22type%22%2C%22team%22%5D`. The tool's param description notes this.

When a breakdown contains `team`, the team entry in `breakdown_value` is the team ID as a
string. Look it up via the `team_id_options` field in the response, or map to project name
via `posthog:organization-get` (or session context if the agent already has it).

### Prefer `breakdown_value` over `label` for identifying the series

`label` uses the friendly UI name (`"Events"`, `"Identified Events"`), which is lossy.
`breakdown_value` carries the canonical identifier (`"event_count_in_period"`,
`"enhanced_persons_event_count_in_period"`) and should be what the agent reasons on.

## Drilling strategy

A typical flow:

1. Call `billing-usage-retrieve` with `breakdowns=["type","team"]` to get per-product-per-project.
2. Find the item in `results` with the biggest anomaly in `data`.
3. Read its `breakdown_value` to get the (usage type, team id) pair.
4. For events specifically, call `execute-sql` against that team's `events` table in the anomaly's date range to find which specific events drove the volume.
