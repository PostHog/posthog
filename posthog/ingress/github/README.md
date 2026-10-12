# GitHub

Deliveries from the GitHub Apps PostHog runs.

## Headers

- `X-Hub-Signature-256` carries the signature.
- `X-GitHub-Delivery` carries the delivery id.
- `X-GitHub-Event` carries the event type.

## Signature scheme

HMAC-SHA256 over the raw body, hex encoded, with the prefix `sha256=`.
GitHub sends no timestamp, so there is no replay window.

## Delivery id and event type

Both come from headers, never from the body.
A request without `X-GitHub-Delivery` gets no delivery id and skips dedup.
The payload's `installation.id` goes into the delivery context as `installation_id`.

## Apps and secrets

Two apps share this incarnation, each subscribed to its own event types in GitHub.

- `posthog`, the customer-facing App. Its secret is the instance setting `GITHUB_WEBHOOK_SECRET`, so an operator can rotate it without a deploy.
- `stamphog`, the review App. Its secret is the Django setting `STAMPHOG_GITHUB_APP_WEBHOOK_SECRET`, because it is instance-wide infrastructure.

A consumer registers against an app name, so the two apps share no consumers.

Each region runs its own `posthog` App, with its own webhook URL and its own secret.
GitHub already delivers an installation's events to the region that holds it.
The `stamphog` App is one App, and one region serves its endpoint.

## Quirks

The status codes are the defaults: 403 on a bad signature, 500 when unconfigured, 202 on success.
The installation lifecycle is a core consumer rather than a product one, because it keeps PostHog's own integration rows in step with GitHub.
A GitHub delivery is never forwarded to the other region, so no consumer here declares `ownership`.
The other region verifies against its own App's secret, so it would answer a replayed delivery 403 and count it as an invalid signature.
An installation this region does not hold is an installation this region never receives deliveries for.
See [Regional forwarding](../README.md#regional-forwarding) for the lane the providers with one callback URL use.

## Consumers

- `posthog/ingress/github/provider.py` registers `installation_lifecycle` and `installation_repositories` on the `posthog` app.
- `products/{tasks,conversations,error_tracking,review_hog,workflows}/backend/webhook_consumers.py` register the product consumers on the `posthog` app.
- `products/stamphog/backend/webhook_consumers.py` registers `stamphog_review` on the `stamphog` app.

The Error Tracking consumer handles opened and edited issues and pull requests from repository owners, members, and collaborators.
It scans descriptions for direct issue links and fingerprint permalinks on the configured PostHog site, then queues team-scoped tasks.
Repeated links and deliveries reuse an existing reference.
Removing a link from a later description does not remove the reference.

### Picking the project

One installation can link to several projects in a region, so `installation.id` never names one project.
A consumer picks its projects in one of two shapes.

**Subscriptions.**
Deliver the event to every project that has its own row for the repository, for example a workflow, a loop trigger, an issue link, or a monitored repository.
Each project set up that row, so each project gets the event.
`installation_team_ids` gives the candidate projects.
Filter them by the product's own row before you act.

**Single owner.**
Some products act as one voice on a repository or pull request: they post the review, approve, or push fixes.
Such a product needs exactly one project per repository.
Enforce this with a unique constraint across projects on (installation id, repository), as `StamphogRepoConfig` does.
Then find the owner through that row.

Never pick a project by order.
The first or lowest-id project on an installation depends on when the projects connected, not on which project should get the event.
The `github-installation-first-team` semgrep rule flags this pattern.

The [Endpoints table](../README.md#endpoints) lists the consumer names per event type.
PR analytics shared by those consumers live in `posthog/github/`, see its README.
