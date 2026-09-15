# Self-driving reports

Every report starts with a Summary tab. Reports with a pull request also have a Changed code tab.
The report text does not repeat the Summary heading.
The title shows the change type and scope. The metadata row shows the time and links to related work.
Priority and reviewer scope remain in the report list. Evidence counts remain in the Evidence section, which starts expanded.

Chat opens the report conversation beside the document, including an existing implementation session when one is available.
Select text in either report view to ask about that passage.
Reports with a PR show Open in GitHub as the first header button, followed by Chat.
Copy-link options are in the More report actions menu. Report actions do not offer canvas creation.

A draft pull request shows the approval and merge controls, a draft note, and a secondary Ready for review button.
Marking a draft ready does not approve or merge it. Existing merge checks still apply.
Eligible pull requests show Refund in the header. The existing feature flag, billing checks, and confirmation dialog still apply.

The report ends with feedback after its evidence, reviewers, and other supporting sections.
The recommendation keeps its boxed layout and its Ask about it and Dismiss controls.

Informational recommendations, including Likely already fixed, use a blue callout. Decisions use an amber callout.
Unread reports show a small blue dot in the list. Open a report to mark it as read without dismissing or resolving it.
Select the dot or use the right-click menu to mark a report as read or unread. Read reports stay in the list.
Read state is saved on this device for the current user and project. It does not sync across devices or recover earlier report visits.
Select Triage mode to review reports in sequence.
Create PR starts the task in the background. Triage advances only after the task starts successfully.
The confirmation offers View task. It does not open a chat panel or navigate away.
Reports with an active implementation task stay in the list with a Creating PR label, but leave the triage queue.
This uses the saved task assignment and survives reopening the app. It does not dismiss, resolve, or change the report read state.
A failed or stopped task, a task that finishes without a PR, or a report waiting for input returns to triage with a status message.
If task status cannot be loaded, the report stays in triage. An attached PR remains available for review.
Task status refreshes in batches while the list is open. Rows use the same status results as triage.
The triage count includes only loaded reports that need a decision. Load more reports to check the next page.
A callback error after task startup does not change a successful start into a failed start. Older servers without task assignments keep their existing queue behavior.
Triage hides the sidebar. Exiting triage or opening a report restores it without changing its saved width or open setting.
Press T from the report list or an open report to start triage when triage is enabled. The shortcut does not run while you type in a field.

To filter reports for a user, open Filter reports, then hover over Scope.
Hover opens the user list without moving keyboard focus. Click the search field to type, or use the keyboard to open Scope and focus the search field.
The search starts empty and shows up to 20 options, including For you and Entire project.
Search by name or email across all users. The search field stays visible above the results.

## Storybook previews

The `Inbox/Reports` stories cover the sidebar, report list, report detail, and triage mode.
They use local report and task fixtures, including active work, failed tasks, and requests for input.
PR stories include draft and failed-check states and a rendered code diff.
Interactive stories cover user search, read state, summary navigation, and sidebar restoration.
The `inbox` story tag selects these previews for visual checks in both themes.
Cloud task startup, refunds, and GitHub writes are not connected to live services in these previews.
