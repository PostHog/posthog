# Report completion and late PR attachments

A report completes after all linked implementation PRs are closed or merged.
At least one merged PR resolves the report; otherwise all closed PRs suppress it.

Only a state read from GitHub completes a report.
A task run writes its own `pr_merged` into its output, and a state from that output, from an agent, or from a legacy assignment is a claim.
A claimed close or merge holds the report open and queues a GitHub read instead (`verify_implementation_pr_state`).
The read stores the real state, which then completes the report or leaves it open.
A report resolved on a merge GitHub later contradicts returns to ready.
To verify stored states in bulk, run `python manage.py reconcile_report_pull_requests --team-id <id>`.

Attaching a new open, draft, or unknown PR to a resolved report returns it to ready.
The shared PR-linking service applies this rule to task outputs and agent attachments.
An existing attachment retry does not reopen a report, and importing legacy assignments preserves its status.
Suppressed reports remain suppressed when another PR is attached.
