# Cost reduction strategies by product

Use these strategies only when they map to what the customer's data actually shows.
Do not recite the full list; pick the 2-4 tactics that are relevant to the pattern you just
investigated. For every recommendation, include the docs link so the user can read more.

## Product analytics

1. **Event optimization**. `$autocapture` often drives 60-80% of event costs. The customer
   can reduce event volume by setting an allow or ignore list.
   See https://posthog.com/docs/product-analytics/autocapture#reducing-events-with-an-allow-and-ignorelist
2. **Identified vs anonymous events**. Identified events are priced 4x anonymous. Check
   whether every identified event actually needs the user context. Landing pages, public
   marketing or docs traffic, and pre-signup activity are common candidates for being
   anonymous. Each event moved from identified to anonymous saves 4x.
   See https://posthog.com/docs/data/anonymous-vs-identified-events
3. **`identify()` call frequency**. It is only necessary to identify a user once per session.
   Check `posthog._isIdentified()` before calling `identify()` to avoid redundant events.
   See https://posthog.com/docs/product-analytics/identify
4. **`group()` call frequency**. If group analytics is enabled, client-side SDKs only need to
   call `group()` once per session.
   See https://posthog.com/docs/product-analytics/group-analytics
5. **`$pageview` and `$pageleave`**. PostHog automatically captures these. For pages that
   do not need them, disable them via `capture_pageview: false` and `capture_pageleave: false`
   in `posthog.init()`, then capture manually only where needed.
6. **Limits and sampling**. Custom spending limits and sampling reduce costs at the cost
   of data fidelity. Discuss the tradeoff before suggesting.
7. **Usage patterns**. Show the user the top 20 events by count for the affected project.
   Events starting with `$` are PostHog defaults.

General cost-reduction hub: https://posthog.com/docs/product-analytics/cutting-costs

## Session replay

1. **Disable automatic recording**. Turn off automatic recording and programmatically start
   and stop recordings based on user behavior or conditions.
   See https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record#programmatically-start-and-stop-recordings
2. **Feature flag gating**. Use feature flags to control which users or sessions get recorded.
   See https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record#with-feature-flags
3. **Minimum recording duration**. Set a minimum session duration to avoid capturing very
   short sessions that are unlikely to be useful.
   See https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record#minimum-duration
4. **Sampling**. Use sampling rates to record only a percentage of sessions.
   See https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record#sampling

General cost-reduction hub: https://posthog.com/docs/session-replay/cutting-costs

## Feature flags

Feature flags are billed based on `/flags` endpoint requests, NOT on `$feature_flag_called`
events. The event is optional and only used for metrics.

1. **Client-side request optimization**. Configure `advanced_disable_feature_flags_on_first_load: true`
   to reduce redundant flag requests, especially when calling `posthog.identify()` immediately
   after page load.
2. **Bootstrap feature flags**. Use bootstrapping to load flags exactly once instead of
   automatic requests. Set `advanced_disable_feature_flags: true` and implement bootstrapping.
   See https://posthog.com/docs/feature-flags/bootstrapping
3. **Survey-only evaluation**. If flags are only needed for surveys, set
   `advanced_only_evaluate_survey_feature_flags: true` to disable other flag evaluations.
4. **Local evaluation for server-side flags** (usually the biggest win). Evaluate flags
   locally instead of making API requests per flag. Local evaluation requests cost 10 credits
   but can evaluate flags for hundreds/thousands of users, far more efficient than individual
   API calls. See https://posthog.com/docs/feature-flags/local-evaluation
5. **Polling interval**. Increase the local-evaluation polling interval from the default
   30 seconds to reduce definition fetch frequency.
6. **Avoid edge/Lambda local evaluation**. Do not use local evaluation in edge or Lambda
   environments, as it initializes PostHog on every call.
7. **Audit forgotten environments**. Old demos, test apps, or staging servers can silently
   make flag requests. Trend `$feature_flag_called` events broken down by `$lib`,
   `$lib_version`, `$host` to identify unexpected environments.

General cost-reduction hub: https://posthog.com/docs/feature-flags/cutting-costs

## Error tracking

1. **Configure exception autocapture**. Disable unnecessary exception types (e.g. console
   errors) via `capture_exceptions` settings in the JS SDK.
2. **Suppression rules**. Set up client-side suppression rules to filter unwanted exceptions
   based on type and message.
3. **Burst protection**. Adjust rate limiting settings (`__exceptionRateLimiterBucketSize` and
   `__exceptionRateLimiterRefillRate`) to prevent excessive capturing from loops.
4. **`before_send` hook**. Filter exceptions client-side before they are captured.
5. **Issue suppression**. Mark recurring unwanted issues as "Suppressed" to prevent future
   exceptions of the same type from being ingested.

General cost-reduction hub: https://posthog.com/docs/error-tracking/cutting-costs

## Data warehouse

1. **Incremental syncing**. Use incremental over full table replication. Full replication
   is only needed for syncing deletions or tables without incrementing fields.
   See https://posthog.com/docs/cdp/sources#incremental-vs-full-table
2. **Replication keys**. Use `updated_at` timestamps or autoincrementing IDs as replication
   keys for incremental syncing.
3. **Sync frequency**. Adjust how often tables sync on the sources page to reduce unnecessary
   data transfers. See https://posthog.com/docs/cdp/sources#syncing
4. **Disable unused tables**. Turn off syncing for tables the customer does not use.

General sources docs: https://posthog.com/docs/cdp/sources

## General considerations

1. **Special events**. Several events are excluded from the billable events product and
   billed in their own product instead:
   - `$feature_flag_called` → `feature_flag_requests`
   - `$exception` → error tracking
   - `survey sent`, `survey shown`, `survey dismissed` → surveys (note: no `$` prefix,
     spaces in the name)
   - `$ai_generation`, `$ai_embedding`, `$ai_span`, `$ai_trace`, `$ai_metric`,
     `$ai_feedback`, `$ai_evaluation`, `$ai_trace_summary`, `$ai_generation_summary`,
     `$ai_trace_clusters`, `$ai_generation_clusters` → `llm_analytics` / `ai_credits`

   Do not recommend disabling any of these as an events-product cost reduction lever —
   they already don't count toward that product. See
   `references/billing-nuances.md` and `posthog/tasks/usage_report.py` for the source
   of truth.

2. **Billing limits**. Custom spending limits per product prevent unexpected costs.
3. **Quota limiting timing**. After increasing or removing spending limits, it can take
   15-30 minutes for the limit to reset. The quota-limiting job runs every 15 minutes.
4. **Startup program**. If the customer is in the startup program, some billing tactics
   matter less until the program expires. Check `billing_context.startup_program_label`.
