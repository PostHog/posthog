# Data deletion requests

How PostHog staff delete a customer's data by event type, property, or person — without customer SQL.

Selective deletion is a built-in flow, not a bespoke ClickHouse project.
An operator fills in a request, and a scheduled job runs the deletes and verifies the rows are gone.
A small request needs no human approval at all.

The flow lives in Django admin today.
There is no customer-facing API or UI yet.
Whether to expose it to customers is a separate product decision.

## What it can delete

`DataDeletionRequest` (`posthog/models/data_deletion_request.py`) has three request types:

| `request_type`     | What it removes                                              |
| ------------------ | ------------------------------------------------------------ |
| `event_removal`    | Whole events that match the criteria.                        |
| `property_removal` | Named properties from matching events (the event stays).     |
| `person_removal`   | A set of persons: their profiles, events, and/or recordings. |

This document focuses on `event_removal`, the type support most often needs — for example, "delete every `$pageview` for team X between two dates."

## Request fields

An `event_removal` request is defined by a few fields:

- `team_id` — the team whose data is deleted. One request belongs to one team and cannot be retargeted.
- `start_time` and `end_time` — the time range. `start_time` must be before `end_time`.
- `events` — the event names to delete, one or more. Leave this empty and set `delete_all_events` to delete every event in the range.
- `hogql_predicate` — an optional HogQL boolean expression that narrows the match further, for example `properties.$browser = 'Chrome'`. It is validated against the events table when the request is saved.

No customer-written SQL is needed.
The operator lists the event names and the range; the job builds and runs the deletes.

## Lifecycle

A request moves through these statuses:

`draft` → `pending` → `approved` → `in_progress` → `completed`

- **draft** — the operator is still editing. Changing any criteria on a submitted request resets it to `draft` and clears its stats.
- **pending** — submitted, waiting for approval.
- **approved** — cleared to run, either by a person or by the auto-approval job.
- **in_progress** — the Dagster job is running the deletes.
- **completed** — the rows are gone and verification confirmed it. A deferred request passes through **queued** first (see below).
- **failed** — an execution attempt errored. A ClickHouse Team member can retry it.

## Auto-approval

ClickHouse deletes are heavyweight mutations that can slow queries and grow disk use while they run.
Approval exists so a person can schedule large ones for a quiet window.

A small request does not need that.
The auto-approval sweep job approves a `pending` `event_removal` request without a person when all of these hold:

- The submitter did not opt into manual approval (`requires_approval` is false).
- Its time range has closed, so a count taken now bounds what the deferred drain will delete.
- Its matching event count is below `AUTO_APPROVE_MAX_EVENTS`, which is **100,000**.

The sweep runs every `AUTO_APPROVE_INTERVAL_MINUTES`, which is **30 minutes**.
It refreshes each candidate's ClickHouse stats first, so the size decision uses a count it just measured.
A request under the limit is approved as **deferred** (see below).

So a request that deletes one event type across a closed date range, matching fewer than 100,000 events, is approved and run without any human review, usually within 30 minutes of submission.

Both constants live in `posthog/models/data_deletion_request.py`.
Change them there.

## Immediate versus deferred execution

Approval also picks how the delete runs. Only `event_removal` supports both modes.

- **Immediate** — the job runs a dedicated lightweight delete mutation now, one shard at a time.
- **Deferred** — the job queues the matching event UUIDs into `adhoc_events_deletion`. The scheduled `deletes_job` drains that queue alongside the other deletions, and a verify sweep promotes the request to `completed` once no matching rows remain.

Auto-approved requests are always deferred.
A person approving manually chooses the mode.

## Timing — what to tell a customer

The execution path is scheduled work, not on-demand.
Give an honest window, not an instant answer and not a multi-week estimate.

- A small auto-approvable request is normally approved within **30 minutes** of submission (the sweep interval), then runs on the next execution tick.
- A **deferred** request completes when the scheduled `deletes_job` next drains the queue. That drain runs on a weekly cadence, so a deferred request can take up to about a week to reach `completed`.
- An **immediate** request runs as soon as an operator approves it and the pickup sensor launches the job.
- A large or complex request that needs manual review waits on a person, plus the run itself.

Selective deletion does **not** require a bespoke multi-week ClickHouse project.
The scope and mode set the timing.

## Where the flow runs

- Model and business rules: `posthog/models/data_deletion_request.py`
- Django admin (submit, approve, retry, verify): `posthog/admin/admins/data_deletion_request_admin.py`
- Dagster jobs, the pickup sensor, the auto-approval schedule, and the verify sweep: `posthog/dags/data_deletion_requests.py`
- Which ClickHouse tables a deletion reaches: [clickhouse-deletion-coverage.md](./clickhouse-deletion-coverage.md)

## Lifecycle analytics

The flow reports lifecycle events to PostHog's own analytics project through `posthog/ph_client.py`, so the team can measure how many requests we field and how long each takes.
These events describe internal operations; they do not touch the customer's project data.

| Event                             | When it fires                                  |
| --------------------------------- | ---------------------------------------------- |
| `data deletion request submitted` | A draft is submitted for approval.             |
| `data deletion request approved`  | Approved by a person or the auto-approval job. |
| `data deletion request completed` | Verification confirmed the rows are gone.      |
| `data deletion request failed`    | An execution attempt errored.                  |

Every event carries `request_id`, `team_id`, `request_type`, `matching_event_count`, and timings (`seconds_since_created`, `seconds_since_approved`), so volume and turnaround are both measurable.
The `approved` event carries `approved_via`, which is `auto` or `manual`.
