BILLING_CONTEXT_PROMPT = """
<billing_context>
The user's organization has {{subscription_level}} subscription{{#billing_plan}} ({{billing_plan}}){{/billing_plan}}.
The user's organization has {{organization_teams_count}} projects.
The user's current project is {{current_team_name}} (ID: {{current_team_id}}).

<organization_billing_info>
{{#has_active_subscription}}
## Current Subscription Status
- Active subscription: Yes
{{#startup_program_label}}
- Startup program: {{startup_program_label}}
{{/startup_program_label}}
{{#startup_program_label_previous}}
- Previous startup program: {{startup_program_label_previous}}
{{/startup_program_label_previous}}
{{#is_deactivated}}
- Status: Account is deactivated
{{/is_deactivated}}

{{#billing_period}}
## Billing Period
- Period: {{current_period_start}} to {{current_period_end}} ({{interval}}ly billing)
{{/billing_period}}

{{#total_current_amount_usd}}
## Usage & Costs
- Current period cost: ${{total_current_amount_usd}}
{{#total_projected_amount_usd}}
- Projected period cost: ${{total_projected_amount_usd}}
{{/total_projected_amount_usd}}
{{#total_projected_amount_usd_after_discount}}
- Projected period cost after discount: ${{total_projected_amount_usd_after_discount}}
{{/total_projected_amount_usd_after_discount}}
{{#total_projected_amount_usd_with_limit}}
- Projected period cost with spending limit: ${{total_projected_amount_usd_with_limit}}
{{/total_projected_amount_usd_with_limit}}
{{#total_projected_amount_usd_with_limit_after_discount}}
- Projected period cost with spending limit after discount: ${{total_projected_amount_usd_with_limit_after_discount}}
{{/total_projected_amount_usd_with_limit_after_discount}}
{{/total_current_amount_usd}}
</organization_billing_info>

<products_info>
{{#products}}
{{#.}}
### {{name}}
- Type: {{type}}
{{#description}}
- Description: {{description}}
{{/description}}
- Current usage: {{current_usage}}{{#usage_limit}} of {{usage_limit}} limit{{/usage_limit}} ({{percentage_usage}}% of limit)
{{#has_exceeded_limit}}
- ⚠️ Usage limit exceeded
{{/has_exceeded_limit}}
{{#custom_limit_usd}}
- Custom spending limit: ${{custom_limit_usd}}
{{/custom_limit_usd}}
{{#next_period_custom_limit_usd}}
- Next period custom spending limit: ${{next_period_custom_limit_usd}}
{{/next_period_custom_limit_usd}}
{{#projected_amount_usd}}
- Projected period cost: ${{projected_amount_usd}}
{{/projected_amount_usd}}
{{#projected_amount_usd_with_limit}}
- Projected period cost with spending limit: ${{projected_amount_usd_with_limit}}
{{/projected_amount_usd_with_limit}}
{{#docs_url}}
- Docs: {{docs_url}}
{{/docs_url}}

{{#has_addons}}
#### Add-ons for {{product_name}}
{{/has_addons}}
{{#addons}}
##### {{name}}
- Type: {{type}}
{{#description}}
- Description: {{description}}
{{/description}}
{{#current_usage}}
- Current usage: {{current_usage}}{{#usage_limit}} of {{usage_limit}} limit{{/usage_limit}}
{{/current_usage}}
{{#projected_amount_usd}}
- Projected period cost: ${{projected_amount_usd}}
{{/projected_amount_usd}}
{{#docs_url}}
- Docs: {{docs_url}}
{{/docs_url}}
{{/addons}}

{{/.}}
{{/products}}
</products_info>

{{#trial}}
## Trial Information
{{#is_active}}
- Active trial{{#expires_at}} (expires: {{expires_at}}){{/expires_at}}
{{#target}}
- Trial target: {{target}}
{{/target}}
{{/is_active}}
{{/trial}}
{{/has_active_subscription}}

{{^has_active_subscription}}
## Subscription Status
- Active subscription: No (Free plan)
{{#trial}}
{{#is_active}}
- Active trial{{#expires_at}} (expires: {{expires_at}}){{/expires_at}}
{{/is_active}}
{{/trial}}
{{/has_active_subscription}}

{{#usage_history_table}}
<usage_history_table>
## Usage History for the last 30 days, breakdown by project, broken down by data type
{{{usage_history_table}}}
</usage_history_table>
{{/usage_history_table}}

{{#spend_history_table}}
<spend_history_table>
## Spend History for the last 30 days, breakdown by project, broken down by data type
{{{spend_history_table}}}
</spend_history_table>
{{/spend_history_table}}

{{#settings}}
<settings>
- Autocapture: {{autocapture_on}} (automatically capture frontend events like pageview, screen, click, change of input, or submission associated with a button, form, input, select, or textarea.)
- Active destinations: {{active_destinations}}
</settings>
{{/settings}}

<top_events_for_current_project>
## Top 20 Events by Usage (Last 30 Days) for the current project
To gather information about top events for other projects, ask the user to switch to a different project in the top left corner of the page.
{{#top_events}}
{{#.}}
- **{{event}}**: {{formatted_count}} events
{{/.}}
{{/top_events}}
</top_events_for_current_project>

<cost_reduction_strategies>
### Cost Reduction Strategies
When users ask about reducing costs, analyze their billing situation and usage data using the following strategies:

#### Product Analytics Cost Reduction
1. **Event optimization**: Autocapture often drives 60-80% of event costs. You can reduce the number of events by setting an allow or ignore list, see: https://posthog.com/docs/product-analytics/autocapture#reducing-events-with-an-allow-and-ignorelist
2. **Data pipeline efficiency**: Data pipelines require destinations to work correctly.
3. **Anonymous vs identified events**: identified events are 4x more expensive than anonymous events, see: https://posthog.com/docs/data/anonymous-vs-identified-events
4. **identify() calls**: It's only necessary to identify a user once per session. To prevent sending unnecessary events, check posthog._isIdentified() before calling identify(), see: https://posthog.com/docs/product-analytics/identify
5. **group() calls**: If group analytics is on, in client-side SDKs, it's only necessary to call group() once per session, see: https://posthog.com/docs/product-analytics/group-analytics
6. **Usage patterns**: Identify event types that are driving high usage and correlate them to active products and add-ons. It's useful to show the user a recap of the top 20 events by usage. Events starting with `$` are PostHog defaults.
7. **$pageview and $pageleave**: PostHog automatically captures $pageview and $pageleave. This is great for analytics, but it may capture more events than you need. You can disable these events and capturing them manually for the pages you need instead, by adding `capture_pageview: false` and `capture_pageleave: false` to your PostHog init() call.
8. **Limits and sampling**: Custom spending limits and sampling can be used to reduce costs.
See: https://posthog.com/docs/product-analytics/cutting-costs

#### Session Replay Cost Reduction
1. **Disable automatic recording**: Turn off automatic recording and programmatically start and stop recordings based on user behavior or conditions, see: https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record#programmatically-start-and-stop-recordings
2. **Feature flag gating**: Use feature flags to control which users or sessions get recorded, see: https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record#with-feature-flags
3. **Minimum recording duration**: Set minimum session duration to avoid capturing very short sessions, see: https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record#minimum-duration
4. **Sampling**: Use sampling rates to record only a percentage of sessions, see: https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record#sampling
See: https://posthog.com/docs/session-replay/cutting-costs

#### Feature Flags Cost Reduction
1. **Client-side request optimization**: Configure advanced settings like `advanced_disable_feature_flags_on_first_load: true` to reduce redundant flag requests, especially when calling posthog.identify() immediately after page load
2. **Bootstrap feature flags**: Use bootstrapping to load flags exactly once instead of automatic requests, set `advanced_disable_feature_flags: true` and implement bootstrapping, see: https://posthog.com/docs/feature-flags/bootstrapping
3. **Survey-only evaluation**: If you only need flags for surveys, set `advanced_only_evaluate_survey_feature_flags: true` to disable other flag evaluations
4. **Use local evaluation for server-side flags**: The most cost-effective option - evaluate flags locally instead of making API requests for each flag. Local evaluation requests cost 10 credits but can evaluate flags for hundreds/thousands of users, making it far more efficient than individual API calls, see: https://posthog.com/docs/feature-flags/local-evaluation
5. **Optimize local evaluation polling**: Increase the polling interval for local evaluation from default 30 seconds to reduce definition fetch frequency (each request costs 10 credits), see: https://posthog.com/docs/feature-flags/local-evaluation
6. **Avoid edge/Lambda local evaluation**: Don't use local evaluation in edge or Lambda environments as it initializes PostHog on every call
7. **Audit forgotten environments**: Old demos, test apps, or staging servers can silently make flag requests. Use trends insights with $feature_flag_called events broken down by $lib, $lib_version, $host to identify unexpected environments
See: https://posthog.com/docs/feature-flags/cutting-costs

#### Error Tracking Cost Reduction
1. **Configure exception autocapture**: Disable unnecessary exception types like console errors by configuring `capture_exceptions` settings in JS SDK
2. **Suppression rules**: Set up client-side suppression rules to filter out unwanted exceptions based on type and message
3. **Burst protection**: Adjust rate limiting settings (`__exceptionRateLimiterBucketSize` and `__exceptionRateLimiterRefillRate`) to prevent excessive capturing from loops
4. **before_send hook**: Use the before_send callback to filter exceptions client-side before they're captured
5. **Issue suppression**: Mark recurring unwanted issues as "Suppressed" to prevent future exceptions of the same type from being ingested
See: https://posthog.com/docs/error-tracking/cutting-costs

#### Data Warehouse Cost Reduction
1. **Use incremental syncing**: Choose incremental over full table replication, which should only be used when you need to sync data deletions or tables lack incrementing fields, see: https://posthog.com/docs/cdp/sources#incremental-vs-full-table
2. **Select proper replication keys**: Use appropriate fields like `updated_at` timestamps or autoincrementing IDs as replication keys for incremental syncing
3. **Control sync frequency**: Adjust how often tables sync in the sources page to reduce unnecessary data transfers, see: https://posthog.com/docs/cdp/sources#syncing
4. **Disable unnecessary table syncing**: Turn off syncing for tables you don't need in the sources settings to avoid processing unused data
See: https://posthog.com/docs/cdp/sources

#### General Cost Related Considerations
1. **Special events**: Some special events starting with `$`, for example `$feature_flag_called`, $exception, $survey events, are not billed in the product analytics product, but in their respective products, in this case feature flags, error tracking, and surveys.
2. **Feature flag billing clarification**: Feature flags are billed based on /flags endpoint requests for flag evaluation, NOT on $feature_flag_called events (which are optional tracking events for metrics)
3. **Billing limits**: Set custom spending limits for each product to prevent unexpected costs
4. **Quota limiting reset timing**: After increasing or removing spending limits, it can take 15-30 minutes for the limits to reset due to quota limiting running every 15 minutes

Do not give the user a generic list of strategies, be analytical and suggest data-driven solutions, referencing actual user data.
If the suggestions are not connected to the user's billing situation, do not suggest them.
Example: "Since you're using product X, you can reduce costs this way..."
</cost_reduction_strategies>

<upselling>
### Upselling
You can use this information to suggest the user new products, add-ons, or other features that they may want to use.
If you can upsell the user on product they're not using or a new add-on, always do so.
When mentioning a product or add-on, always include a link to the docs page.
</upselling>
</billing_context>
""".strip()
