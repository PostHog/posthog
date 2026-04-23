# Billing nuances

Non-obvious facts about how PostHog bills that the agent should know before explaining
costs to a customer. Each of these trips up first-time analyzers.

## Special `$`-prefixed events are billed in the right product, not product analytics

Some events starting with `$` are NOT counted against product analytics event volume:

- `$feature_flag_called` — tracked in feature flags product (but see next point)
- `$exception` — counted in error tracking product
- `$survey_shown`, `$survey_sent`, `$survey_dismissed` — counted in surveys product

When a customer asks "why is my event volume so high", inspect whether a lot of the counted
events are these special ones. If so, the product analytics bill should not be affected;
the real cost is in the other product.

## Feature flags are billed by `/flags` requests, not events

Feature flag cost comes from `/flags` endpoint requests (for flag evaluation), NOT from
`$feature_flag_called` events. The event is optional. If the customer has disabled the event
but is still making flag requests, they are still being billed.

This matters because:

- "Stop sending `$feature_flag_called`" does NOT reduce flag costs
- Reducing flag costs requires reducing evaluation requests (local evaluation, bootstrapping,
  disabling on first load, etc.)

## Identified events cost 4x anonymous events

In product analytics, identified events (those with a `distinct_id` that has been associated
with a user via `identify()`) are priced at 4x the rate of anonymous events. If a spike is
specifically in identified events, the relevant question is "does every event actually need
to be identified".

## Quota limit reset takes 15-30 minutes

After a customer increases or removes their custom spending limit, the limit does not reset
immediately. The quota-limiting job runs every 15 minutes, so it can take up to 30 minutes
for the new limit to take effect. If the customer just changed limits and expects immediate
results, warn them about this.

## Startup program distorts the picture

If `billing_context.startup_program_label` is set, the customer is getting credits under
PostHog's startup program. Their effective cost does not fully reflect their usage until
the program expires. When analyzing spend:

- Normal cost-reduction tactics still work, but the urgency is lower
- Tell the customer the program's expiry date and what their bill might look like then

## `autocapture` is the single biggest event-volume driver on most accounts

PostHog captures `$autocapture`, `$pageview`, `$pageleave`, `$rageclick`, etc. automatically.
On a typical account these account for 60-80% of event volume. Before suggesting any of the
subtler cost reductions, always verify what fraction of the customer's events are
autocapture-generated.

## Projections vs current usage

`billing-list` returns both `total_current_amount_usd` (period-to-date) and
`projected_total_amount_usd` (forecast for the full period). When a customer says "my bill
is too high", clarify whether they mean:

- Their period-to-date charge so far
- The projected total they'll pay at the end of the period
- The bill they already received for a previous period

Spike investigation is most useful for case 1 and 2. For case 3, the data is in
`billing-list.previous_bills` or in Stripe, not in the usage/spend endpoints.
