# GitHub issue comments

The Inbox setting `github_issue_writeback_enabled` lets a project post public comments on GitHub issues that contributed to a ready report.
The setting defaults to `false`.
Each comment contains a report link and a stable marker. It contains no report title or research.
The report requires project access.

The notification workflow sends the report notification before it starts a separate GitHub activity.
The activity has a five-minute timeout and uses the BATCH request priority.
It runs on later report settles too, so an issue added after the first notification can receive a comment.
The worker checks the current GitHub issue state before posting and skips closed issues, locked issues, and pull requests.

One `SignalReportGithubComment` row claims each report and issue.
`commented_at` records a confirmed comment. A pending claim has a null value.
The worker keeps pending claims after network failures because GitHub can accept a comment before the response is lost.
After ten minutes, a later settle can claim the pending row and search the issue comments for the stable marker.
An existing marker completes the claim without a second POST.
A complete read without the marker permits a retry.
The search stops after ten pages of 100 comments. An incomplete or failed read leaves the claim pending.
This recovery is best effort. GitHub does not provide an atomic idempotency key for comment creation.

Use the `signals.github_writeback_failed` log to diagnose request failures.
The `signals.github_writeback_posted` log records the report, project, candidate issues, and comments posted.
An activity timeout appears as `inbox notification: GitHub write-back failed` in the workflow log.
Pending claims retry only when the report settles again. There is no periodic recovery job.
