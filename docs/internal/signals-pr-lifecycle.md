# Report completion and late PR attachments

A report completes after all linked implementation PRs are closed or merged.
At least one merged PR resolves the report; otherwise all closed PRs suppress it.

Attaching a new open, draft, or unknown PR to a resolved report returns it to ready.
The shared PR-linking service applies this rule to task outputs and agent attachments.
An existing attachment retry does not reopen a report, and importing legacy assignments preserves its status.
Suppressed reports remain suppressed when another PR is attached.

## Verification plans

After research completes, actionable reports can include a `Verification plan` note for the implementation agent.
This final request is optional: if generation or note conversion fails, research still completes without the note.
The findings, actionability, priority, title, and summary remain available.
Core research failures and cancellation still fail the run and trigger session cleanup.

The plan separates `Confirm the current state` guidance from `Confirm the outcome` guidance.
Each section says what evidence to collect, which result supports a conclusion, and which result is inconclusive.
The guidance can use a query, test, log search, replay, code review, or manual check, and does not prescribe a resolution.
Report retrieval directs any agent to the work log, where verification guidance applies regardless of how the agent started.
The agent checks that the note matches the current findings and confirms the current state before it starts work.
It confirms the outcome after the chosen resolution.
If current evidence shows the issue is gone, it records that result and stops; if no note applies, it verifies the issue from the report's evidence.
Missing data, failed checks, and inconclusive results do not establish that the issue is fixed.

## Opening a report task

When a report has a linked task run, the View task button opens it in the PostHog AI sidebar.
The button fits its label, including when it appears below the Solution section.
