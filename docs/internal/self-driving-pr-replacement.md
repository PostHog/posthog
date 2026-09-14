# Replacing an automated Self-driving PR

When new research changes a report's proposed fix, Self-driving can start a replacement implementation and close the selected obsolete PRs after the replacement succeeds. The report activity log distinguishes a recommendation, a started replacement, and its outcome.

## Which PRs qualify

Only a PR created by an automatically started Self-driving implementation run qualifies. The server records the exact run ID and generated branch in its protected `task_run` artefact. The run must be completed, cloud-based, and in background mode; its protected implementation stage and branch must agree with that receipt. GitHub must confirm an open, unmerged PR from that branch in the same repository, and the run must report that PR as output.

User-started Implement runs, interactive runs, manual background runs, manual attachments, and historical runs without this receipt are ineligible. Any later run on the same task also excludes its earlier automated run, so a manual continuation cannot inherit permission to replace work. A human claim blocks automatic replacement.

Research receives only verified candidates. It selects the obsolete subset and explains why; the server binds those URLs to their task, exact run, automation receipt, claim, head SHA, and research pass. An unknown URL invalidates the assessment. A report already addressed by other work cannot start a replacement.

## How reports, tasks, and PRs connect

The existing `task_run` artefact associates a task and run with a report. A `pull_request` artefact links the report to a shared `SignalReportPullRequest` record and carries task and claim attribution. The canonical PR reader also supports legacy links and run outputs. Being linked to a report alone does not prove automatic creation.

Replacement bookkeeping uses existing `SignalReportArtefact` rows:

| Artefact                     | Purpose                                                                          |
| ---------------------------- | -------------------------------------------------------------------------------- |
| `implementation_decision`    | Research recommendation, exact predecessor subset, and verified research context |
| `implementation_replacement` | Immutable decision snapshot, replacement task/run, and transferred claim         |
| `implementation_handover`    | Append-only progress and final outcome, including per-PR closure results         |

These records and automation receipts cannot be created, edited, or deleted through the generic artefact API. There is no additional lifecycle model or replacement state in `TaskRun.state`.

## Starting and finishing the handover

The report row lock serializes claim transfer and replacement creation. The decision must belong to the current completed research pass. The server releases only the selected automated predecessor's claim, creates the replacement task and claim, and stamps `implemented_at_run_count` so the same pass cannot start another replacement. An unrelated claim or pending replacement blocks creation. Existing autonomy, priority, quota, and billing gates continue to apply.

Opening a PR does not close its predecessors. Reconciliation waits for the exact replacement run to complete successfully and for all its reported PRs to be linked and verified open. Each replacement PR must also match its automatic-run receipt and generated branch. Before each selected predecessor closes, the server rechecks its provenance, head SHA, replacement PRs, report research/status, and ownership. A PR used by another active report stays open.

Task status/output changes, report changes, claim changes, and PR reconciliation trigger handover reconciliation. A report cannot finish from predecessor closures while a replacement is pending. After handover ends, the existing all-PR completion rules apply.

## Failures and retries

A failed or cancelled run preserves predecessors and releases only its own replacement claim. Missing replacement output is retried up to five attempts, then recorded as failed with that claim released. Changed ownership or report status cancels handover. Changed research, an unverifiable replacement, or a changed predecessor leaves work for review. Successful closures remain recorded even if another target needs attention.

Processing artefacts hold a five-minute lease and worker token. A delayed wake-up recovers a worker that dies after reservation; retries reuse recorded per-PR results. A complete conversation-comment lookup checks the handover marker before posting another explanation. Internal processing records are hidden from the activity log; final outcomes show the actual PR links and which targets were closed or retained.

GitHub does not provide an atomic compare-SHA-and-close operation. The final checks run after posting the explanation and immediately before closure, but an external mutation in that last interval remains possible.
