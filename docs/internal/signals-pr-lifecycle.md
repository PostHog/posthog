# Report completion and late PR attachments

A report completes after all linked implementation PRs are closed or merged.
At least one merged PR resolves the report; otherwise all closed PRs suppress it.

Attaching a new open, draft, or unknown PR to a resolved report returns it to ready.
The shared PR-linking service applies this rule to task outputs and agent attachments.
An existing attachment retry does not reopen a report, and importing legacy assignments preserves its status.
Suppressed reports remain suppressed when another PR is attached.

## Report chat

The report's **Implement** and **Ask AI** actions use the PostHog AI sidebar without leaving the report.
The sidebar shows the report title and attaches its identifier as untrusted context.
That context stays with the chat when the reader selects a different report.
**Ask AI** opens a composer without starting a task.
Selecting a suggested question or action sends it immediately.
Typed questions still require **Send** or Command/Ctrl + Enter.
Consent checks, report state checks, task limits, and task-to-report links also apply to sidebar runs.

When a linked task is active, **View task** replaces **Implement** and opens that task's existing run in the sidebar.
An implementation task that produced a pull request also keeps this link.
Opening the link does not create a task or send another message.
Task chats remember the last visible message for the current browser session.
After a page reload, or if that message is no longer available, the chat opens at its latest user message.
If an implementation fails without a pull request, **Implement** becomes available again when the report remains eligible.
