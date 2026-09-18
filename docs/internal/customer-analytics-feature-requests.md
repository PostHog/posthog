# Customer Analytics feature request GitHub links

A feature request can link to one GitHub issue through a GitHub integration connected to the same project.

## Behavior

- Linking and resuming sync fetch the current issue through the selected GitHub App integration.
- The integration must be active, belong to the project, still reference the saved installation, and be visible to the person linking or resuming sync.
- Feature request responses and history include GitHub link metadata only when the person can view the integration. Other history changes remain visible.
- GitHub issue URLs use `https://github.com/<owner>/<repo>/issues/<number>`. Pull request URLs are rejected. Comment fragments do not affect the saved link.
- Closing an issue with reason `completed` marks the request Completed. Legacy closures without a reason also map to Completed.
- Closing an issue with reason `not_planned` marks the request Won't fix. Unsupported closure reasons do not change the request.
- Reopening restores the request status that existed before GitHub closed it.
- A manual request status update pauses GitHub sync and clears the saved pre-close status. Resuming a closed issue saves the current manual status as the new restore point.
- Pause sync preserves the pre-close status. If the issue reopens while paused, Resume sync restores that status.
- GitHub never overwrites the request title or description. Multiple requests can link to the same issue.
- GitHub metadata-only updates refresh the link without changing the request version, update timestamp, attribution, or history. Status and sync-control changes still update the request.
- Unlink issue preserves the request status and history. An existing link must be removed before another issue can be linked.
- Link, pause, resume, unlink, and GitHub status changes are recorded in feature request history. GitHub-sourced history uses `change_source: "github"`.
- Archived requests reject link controls. Background updates for archived requests do nothing.

## Delivery and limits

The GitHub ingress consumer queues installation ID, repository, issue number, title, state, close reason, and GitHub update time.
It also carries the GitHub delivery ID and receipt time for correlation.
It never queues issue bodies.

The worker finds all matching project-scoped links for an installation.
It ignores duplicate and older GitHub snapshots.
When conflicting state changes share a timestamp, it fetches the current issue because GitHub timestamps have second precision.
The worker checks the feature flag for the user who last enabled sync, with the same organization and project context as the API.
A deleted user, unavailable integration, archived request, paused link, or disabled flag prevents automatic updates.

The worker processes every matching link before it retries a delivery with a conflicted request. It does not periodically repair missed webhooks.
Pause sync, then select Resume sync to fetch the latest issue state.
Scheduled reconciliation and operator alerts are separate work.

## Tracing a sync

Start with the `X-GitHub-Delivery` value from GitHub's delivery page.
Find the shared `ingress_delivery_dispatch` log by `delivery_id`, then filter product logs by `github_delivery_id` with the same value.
The queue log includes `task_id`. Retries retain that task ID and increment the zero-based `sync_attempt`.

| Event                                      | Meaning                                                                                                                                      |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `feature_request_github_delivery_queued`   | Celery publication returned a task ID. This does not prove that a worker ran.                                                                |
| `feature_request_github_task_started`      | An attempt began. `delivery_age_seconds` measures time since receipt, including retry delays.                                                |
| `feature_request_github_target_applied`    | The target transaction committed. `status_before`, `status_after`, and `changed` describe the request status change.                         |
| `feature_request_github_target_skipped`    | A matched target did not apply the update. Inspect `reason`. Stale and duplicate outcomes use debug level.                                   |
| `feature_request_github_target_conflicted` | A request version changed. Other targets can still update before the delivery retries.                                                       |
| `feature_request_github_target_failed`     | A target failed. Inspect `stage` and `error_type`.                                                                                           |
| `feature_request_github_delivery_summary`  | The attempt reports matched, applied, skipped, conflicted, and failed target counts. Earlier targets can commit even when the attempt fails. |

Target logs include `team_id`, `feature_request_id`, `github_link_id`, and `integration_id`.
The initial query excludes paused links, so `matched=0` does not distinguish a paused link from an unlinked issue.
A `paused` reason means the worker observed a link pause after selecting it.
A successful summary with `applied=0` is not proof of synchronization.

Terminal failures after the three configured retries produce a sanitized `FeatureRequestGitHubTaskFailed` exception in PostHog Error Tracking.
Search its properties by `github_delivery_id` or `task_id`, then inspect the target logs for the failing request.
The exception retains stack locations and records the original exception type, but excludes its message, chain, and local variables.
No new log includes issue titles, bodies, repository URLs, credentials, or raw payloads.

For manual actions, search `feature_request_github_manual_action_committed` by `team_id` and `feature_request_id`.
Link and resume fetch failures use `feature_request_github_issue_fetch_failed`, with the action, request ID, upstream status when available, and a bounded failure stage.
These logs preserve the user-facing validation response.

Verify log and exception delivery with an internal test before expanding the flag.
Reuse the existing Celery metrics for `customer_analytics.process_feature_request_github_issue` when configuring failure alerts.
This instrumentation does not create alerts or add missed-webhook reconciliation.
Do not infer a missed delivery from an old `last_synced_at` alone; an unchanged issue may have no new event.

## Local checks

Run:

```sh
hogli test products/customer_analytics/backend/test/test_feature_request_github.py products/customer_analytics/backend/test/test_feature_request_github_observability.py
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
