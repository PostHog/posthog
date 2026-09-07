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

Fallback reads do not require a data migration. This does not replay webhook
events that were missed before the fix; those reports need a subsequent event
or explicit reconciliation.
