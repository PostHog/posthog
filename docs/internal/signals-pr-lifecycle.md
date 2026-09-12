# Signals implementation PR lifecycle

Report PR lookups use `fetch_implementation_pr_state_for_reports` in
`products/signals/backend/implementation_pr.py`. A non-empty assignment PR takes
precedence. Otherwise, lookup falls back to associated task-run artefacts and
legacy `SignalReportTask` links, or the assignment's task when it has no PR.
Implementation associations take precedence over other PR-bearing associations.
Research, repository-selection, and scout runs do not supply implementation PRs.

List/detail responses, PR checks and review actions, dismissal, and webhook
handling use this selection. Reverse lookup first narrows candidates by PR
identity and task output, then runs the same resolver so a superseded task PR
cannot override an explicit assignment PR.

GitHub webhooks remain scoped to teams connected to the installation. For a
matching task-backed report without an assignment PR, they populate the PR
metadata while preserving any existing claim. Merges resolve matching reports;
unmerged closes suppress them, except reports already resolved. PR-driven
transitions do not enqueue another GitHub close.

Dismissal, snoozing, and manual resolution can close a task-backed fallback PR.
An explicit assignment PR still requires a task or system actor for automatic
closure. The shared-PR guard checks both assignment and task-backed links, and
keeps the PR open while another unfinished report uses it. GitHub must confirm
the PR is open and unmerged before PostHog comments or closes it.

`reviewer_pr_assignment` queues an after-commit task that adds a report's suggested reviewers as GitHub assignees.
It runs when a PR URL first reaches a report, and when a person adds a reviewer to a report that already has a reviewable PR.
Only reviewers who set `github_assign_on_pull_request` on their `SignalUserAutonomyConfig` are assigned, and the default is off.
The task reads the latest `suggested_reviewers` row, so a reviewer removed from the list is not assigned later.
Assignment is additive, so nothing here removes an assignee and a reviewer somebody added by hand stays on the PR.
Closed and merged PRs are skipped.
Every GitHub failure is logged without blocking the sync, the claim, or the reviewer edit that queued it.
One PR can back several reports, and each report queues its own task, so the PR ends up with the union of qualifying reviewers.

`reviewer_pr_ready` queues a second after-commit task that takes the PR out of draft.
Self-driving PRs open as drafts, and a draft only runs a narrowed CI matrix, so a reviewer who wants the full signal has to mark the PR ready and wait for that matrix to start over.
Each suggested reviewer resolves to `github_open_pull_request_ready` on their `SignalUserAutonomyConfig`, falling back to `default_open_pull_request_ready` on `SignalTeamConfig` when it is null, and the PR opens ready if any of them resolves to true.
Reviewers resolve by stored `user_uuid` first and by GitHub login only for entries that carry no uuid, so an org member who never connected GitHub still decides.
A report whose reviewers resolve to no PostHog user follows the team default alone.
Both settings default to draft.
Unlike assignment, this runs only where a PR URL first reaches a report, never on a later reviewer edit, so no later event re-queues it.
GitHub is asked to mark ready through the GraphQL `markPullRequestReadyForReview` mutation, because REST cannot undraft a PR.
That same call reads the PR's timeline and refuses to move a PR whose draft state a person has already moved, which is what makes "a re-drafted PR stays draft" hold even when the queued job runs long after the link.
A PR that is already ready, is closed or merged, or carries the `no-ci` label is left alone, and every GitHub failure is logged without blocking the write that queued it.

Fallback reads do not require a data migration. This does not replay webhook
events that were missed before the fix; those reports need a subsequent event
or explicit reconciliation.
