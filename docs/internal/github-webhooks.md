# GitHub webhooks

Transport is `posthog/ingress/`, which serves every inbound webhook PostHog receives.
Read [`posthog/ingress/README.md`](../../posthog/ingress/README.md) for the response contract, the delivery budget, deduplication, and how to add a consumer.
Only the GitHub-specific parts are below.

## The two Apps

PostHog runs two GitHub Apps, and both are served by the `github` incarnation in `posthog/ingress/github/provider.py`.

**The customer-facing PostHog App**, app name `posthog`.
It delivers to `/webhooks/github/`, and `/webhooks/github/pr/` is an alias for the same view.
Both routes are registered in `posthog/urls.py`.
The secret is the `GITHUB_WEBHOOK_SECRET` instance setting, so an operator can rotate it without a deploy.
The App declares seven event types: `issues`, `issue_comment`, `pull_request`, `pull_request_review`, `installation`, `installation_repositories`, and `push`.

**The Stamphog review App**, app name `stamphog`.
It delivers to `/webhooks/stamphog/github/`, also registered in `posthog/urls.py`, and the view is built in `products/stamphog/backend/facade/webhooks.py`.
The secret is the `STAMPHOG_GITHUB_APP_WEBHOOK_SECRET` environment setting, because the App is instance-wide infrastructure rather than a customer's connection.
The App declares three event types: `pull_request`, `installation`, and `installation_repositories`.

The two Apps are subscribed separately in GitHub, so they declare separate event-type sets rather than one shared superset.
A consumer registers against an app name, and one that registers for an event type its App does not declare fails registry validation.

## Registered consumers

On the `posthog` App:

| Event type                  | Consumers                                 |
| --------------------------- | ----------------------------------------- |
| `issues`                    | `conversations`, `loops`, `workflows`     |
| `issue_comment`             | `conversations`, `loops`, `workflows`     |
| `pull_request`              | `loops`, `tasks_pr_backstop`, `workflows` |
| `pull_request_review`       | `tasks_pr_review`, `workflows`            |
| `push`                      | `loops`, `workflows`                      |
| `installation`              | `installation_lifecycle`                  |
| `installation_repositories` | `installation_repositories`               |

On the `stamphog` App, `stamphog_review` takes all three event types and enqueues the review task.

Each product declares its consumers in `products/<product>/backend/webhook_consumers.py`.
Keep product-specific work behind the product's facade, and keep the product imports deferred so loading the URL configuration does not load every consumer.
Keep consumer names stable when moving code: names are part of the deduplication cache key.

`installation_lifecycle` and `installation_repositories` are core-owned, so no product registers them.
The GitHub incarnation registers them itself as `CORE_CONSUMERS`, and they call `posthog/api/github_callback/installation_events.py`.
They are what keeps PostHog's own integration rows in step with GitHub, which is not one product's business.

Conversations forwards a delivery for an installation this region does not own to the other region.
That runs before the fan-out, because forwarding replays the signed bytes that a consumer never sees.
It does not stop the other consumers from running in this region.

The deduplication key prefix changed from `github_webhook_delivery:` to the generic `webhook_delivery:` when the endpoint moved to ingress.
A manual redelivery inside the 24-hour window that straddles that deploy can therefore reach a consumer twice.
The consumers tolerate it, because each carries its own idempotency underneath the cache mark.

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
Content is omitted unless attribution explicitly enables it with `include_content`.

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

`posthog/github/attribution.py` resolves a GitHub login to an org member.
That lookup runs under `bounded_statement_timeout`, so a slow query degrades to no attribution instead of costing the delivery.
`posthog/github/installations.py` holds the installation and team helpers the attribution and the product lookups share.

## Adding attribution from another product

Resolve the PR within the product's authorized installation and team scope.
Build `PullRequestAttribution` and pass it to the shared emitter from the PR processing path.
Keep product state writes in the product.
When adding another owner to the shared webhook path, resolve ownership before capture so the delivery emits one event.
Wizard artifact matching and lifecycle persistence are separate work.
