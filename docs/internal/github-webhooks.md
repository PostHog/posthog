# GitHub webhooks

The GitHub App sends deliveries to `/webhooks/github/`.
`/webhooks/github/pr/` is an alias for the same view.

## Transport

Transport is `posthog/ingress/`, which serves every inbound webhook PostHog receives.
Read [`posthog/ingress/README.md`](../../posthog/ingress/README.md) for the registry, the delivery budget, deduplication, and the metrics.
Only the GitHub-specific parts are below.

`posthog/urls.py` registers both routes against `build_webhook_view(build_github_provider("posthog"))`.
The secret remains the `GITHUB_WEBHOOK_SECRET` instance setting.
The response is a transport receipt: 202 for every verified delivery, whatever the consumers did.

Each product declares its consumers in `products/<name>/backend/webhook_consumers.py`.
Core owns the installation lifecycle consumers, which the GitHub incarnation registers itself.
Keep product-specific work behind the product's facade.
Product imports remain deferred so loading URL configuration does not load every consumer.
Keep consumer names stable when moving code: names are part of the deduplication cache key.

Conversations forwards a delivery for an installation this region does not own to the other region.
That runs before the fan-out, because forwarding replays the signed bytes that a consumer never sees.
It does not stop the other consumers from running in this region.

## PR analytics

`posthog/github/pull_request_events.py`'s `capture_pr_event` emits `pr_created`, `pr_closed`, `pr_merged`, and `pr_reviewed`.
It accepts a `PullRequestAttribution` value, independent of Task models.
The value carries the source product, team, default actor, groups, and product-specific properties.
A product can supply its own run identifier without creating a Task or implementing another emitter.

The caller owns PR matching, team authorization, event eligibility, and product side effects.
Tasks keeps those operations in `products/tasks/backend/webhooks.py`.
Its review handler ignores bots and accepts submitted reviews.
Signals owns report-assignment updates and GitHub user lookup through its facade.

The shared emitter resolves merger and reviewer attribution and applies common PR properties.
It preserves the caller's default actor when the GitHub user cannot be resolved.
Canonical PR properties, `team_id`, and `pr_source` take precedence over product properties.
Content is omitted unless attribution explicitly enables it.

Passing no attribution uses the external-PR fallback: the first team linked to the installation, in team-ID order.
External events omit PR title, body, labels, requested reviewers, and draft status.

Lifecycle event UUIDs derive from PR URL and event name.
Review UUIDs also include the review ID.
Redeliveries therefore reuse an event UUID.
Repeated close/reopen cycles retain the existing once-per-PR `pr_closed` UUID.
This analytics deduplication does not order product state updates.

Capture is best effort.
Failures increment the existing dropped-event metric and do not prevent subsequent Task effects.
The metric names retain their `posthog_tasks_github_webhook_` prefix for continuity.

## Adding attribution from another product

Resolve the PR within the product's authorized installation and team scope.
Build `PullRequestAttribution` and pass it to the shared emitter from the PR processing path.
Keep product state writes in the product.
When adding another owner to the shared webhook path, resolve ownership before capture so the delivery emits one event.
Wizard artifact matching and lifecycle persistence are separate work.
