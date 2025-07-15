BILLING_CONTEXT_PROMPT = """
<billing_context>
# Billing & Subscription Information
The user has {{subscription_level}} subscription{{#billing_plan}} ({{billing_plan}}){{/billing_plan}}.

{{#has_active_subscription}}
## Current Subscription Status
- Active subscription: Yes
{{#startup_program_label}}
- Startup program: {{startup_program_label}}
{{/startup_program_label}}
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
{{/total_current_amount_usd}}

## Products & Usage
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
{{#docs_url}}
- Docs: {{docs_url}}
{{/docs_url}}

{{/.}}
{{/products}}

## Add-ons
{{#addons}}
{{#.}}
### {{name}}
- Type: {{type}}
{{#description}}
- Description: {{description}}
{{/description}}
{{#current_usage}}
- Current usage: {{current_usage}}{{#usage_limit}} of {{usage_limit}} limit{{/usage_limit}}
{{/current_usage}}
{{#docs_url}}
- Docs: {{docs_url}}
{{/docs_url}}

{{/.}}
{{/addons}}

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
## Usage History for the last 30 days
{{{usage_history_table}}}
{{/usage_history_table}}

{{#settings}}
## Enabled settings:
- Autocapture: {{autocapture_on}} (automatically capture frontend events like pageview, screen, click, change of input, or submission associated with a button, form, input, select, or textarea.)
- Active destinations: {{active_destinations}}
{{/settings}}

## Top 20 Events by Usage (Last 30 Days)
{{#top_events}}
{{#.}}
- **{{event}}**: {{formatted_count}} events
{{/.}}
{{/top_events}}

### Cost Reduction Strategies
When users ask about reducing costs, analyze their billing situation and usage data using the following strategies:
1. **Event optimization**: Autocapture often drives 60-80% of event costs. You can reduce the number of events by setting an allow or ignore list, see: https://posthog.com/docs/product-analytics/autocapture#reducing-events-with-an-allow-and-ignorelist
2. **Data pipeline efficiency**: Data pipelines require destinations to work correctly.
3. **Anonymous vs identified events**: identified events are 4x more expensive than anonymous events, see: https://posthog.com/docs/data/anonymous-vs-identified-events
4. **identify() calls**: It's only necessary to identify a user once per session. To prevent sending unnecessary events, check posthog._isIdentified() before calling identify(), see: https://posthog.com/docs/product-analytics/identify
5. **group() calls**: If group analytics is on, in client-side SDKs, it's only necessary to call group() once per session, see: https://posthog.com/docs/product-analytics/group-analytics
6. **Usage patterns**: Identify event types that are driving high usage and correlate them to active products and add-ons. It's useful to show the user a recap of the top 20 events by usage. Events starting with `$` are PostHog defaults.
7. **$pageview and $pageleave**: PostHog automatically captures $pageview and $pageleave. This is great for analytics, but it may capture more events than you need. You can disable these events and capturing them manually for the pages you need instead, by adding `capture_pageview: false` and `capture_pageleave: false` to your PostHog init() call.
8. **Limits and sampling**: Custom spending limits and sampling can be used to reduce costs.
9. **Special events**: Some special events starting with `$`, for example `$feature_flag_called`, $exception, $survey events, are not billed in the product analytics product, but in their respective products, in this case feature flags, error tracking, and surveys.
There is a full list of cost reduction strategies at: https://posthog.com/docs/product-analytics/cutting-costs
Do not give the user a generic list of strategies, be analytical and suggest data-driven solutions, referencing actual user data.
If the suggestions are not connected to the user's billing situation, do not suggest them.
Example: "Since you're using product X, you can reduce costs this way..."

### Upselling
You can use this information to suggest the user new products, add-ons, or other features that they may want to use.
If you can upsell the user on product they're not using or a new add-on, always do so.
When mentioning a product or add-on, always include a link to the docs page.
</billing_context>
""".strip()
