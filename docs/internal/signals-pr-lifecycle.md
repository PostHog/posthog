# Report completion and late PR attachments

A report completes after all linked implementation PRs are closed or merged.
At least one merged PR resolves the report; otherwise all closed PRs suppress it.

Attaching a new open, draft, or unknown PR to a resolved report returns it to ready.
The shared PR-linking service applies this rule to task outputs and agent attachments.
An existing attachment retry does not reopen a report, and importing legacy assignments preserves its status.
Suppressed reports remain suppressed when another PR is attached.

## An implementation task already holds the report

An implementation task can start while a person has the report open.
If that person then presses Implement, the API returns `429` with the code `signal_report_task_cap`.
The response includes `task_id` only when the person can read the task that holds the report.
This rule also applies when another task prevents a failed task from starting again.

The refusal refreshes the report's task list.
When the response includes `task_id`, the error message offers an Open run action.
The refreshed report keeps the existing Open task action for a task in progress.
