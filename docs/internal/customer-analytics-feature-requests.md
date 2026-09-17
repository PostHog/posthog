# Customer Analytics feature request GitHub links

A feature request can link to one GitHub issue through a GitHub integration connected to the same project.

## Behavior

- Linking and resuming sync fetch the current issue through the selected GitHub App integration.
- The integration must be active, belong to the project, still reference the saved installation, and be visible to the person linking or resuming sync.
- GitHub issue URLs use `https://github.com/<owner>/<repo>/issues/<number>`. Pull request URLs are rejected. Comment fragments do not affect the saved link.
- Closing an issue with reason `completed` marks the request Completed. Legacy closures without a reason also map to Completed.
- Closing an issue with reason `not_planned` marks the request Won't fix. Unsupported closure reasons do not change the request.
- Reopening restores the request status that existed before GitHub closed it.
- A manual request status update pauses GitHub sync and clears the saved pre-close status. Resuming a closed issue saves the current manual status as the new restore point.
- Pause sync preserves the pre-close status. If the issue reopens while paused, Resume sync restores that status.
- GitHub never overwrites the request title or description. Multiple requests can link to the same issue.
- Unlink issue preserves the request status and history. An existing link must be removed before another issue can be linked.
- Link, pause, resume, unlink, and GitHub status changes are recorded in feature request history. GitHub-sourced history uses `change_source: "github"`.
- Archived requests reject link controls. Background updates for archived requests do nothing.

## Delivery and limits

The GitHub ingress consumer queues only installation ID, repository, issue number, title, state, close reason, and GitHub update time. It never queues issue bodies.

The worker finds all matching project-scoped links for an installation.
It ignores duplicate and older GitHub snapshots.
When conflicting state changes share a timestamp, it fetches the current issue because GitHub timestamps have second precision.
The worker checks the feature flag for the user who last enabled sync, with the same organization and project context as the API.
A deleted user, unavailable integration, archived request, paused link, or disabled flag prevents automatic updates.

The worker processes every matching link before it retries a delivery with a conflicted request. It does not periodically repair missed webhooks.
Pause sync, then select Resume sync to fetch the latest issue state.
Scheduled reconciliation and operator alerts are separate work.

## Local checks

Run:

```sh
hogli test products/customer_analytics/backend/test/test_feature_request_github.py
hogli test posthog/ingress/test/
pnpm --filter=@posthog/frontend typescript:check
```

Generate OpenAPI after backend changes with `hogli build:openapi`.
The rollout remains gated by `customer-analytics-feature-requests`.

## Rollout checks

Use an internal test request and an accessible test issue.
Link it, close it as completed, reopen it, and close it as not planned.
Check request history after each transition.
Change the request status manually and confirm that later issue events do not override it until sync resumes.
Repeat a denied write as a viewer.
Do not expand the rollout until missed-webhook recovery and synchronization health checks are available.
