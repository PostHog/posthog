# MCP analytics feedback invitations

The session detail panel offers feedback after 30 seconds with loaded, nonempty tool calls.
Changing sessions, leaving the panel, or hiding the browser tab cancels the delay.
A visible tab starts a fresh delay.
Loading, empty, and impersonated sessions do not receive an invitation.
The survey must be loaded and running before the delay starts.

The invitation opens the same survey as the header's Feedback button.
It does not automatically open a popover or change the survey's questions or targeting.
An invitation starts a 30-day cooldown for that signed-in user in the browser, including when dismissed or left unanswered.
The header button remains available during the cooldown.
The cooldown uses local storage; it does not follow the user across browsers or coordinate simultaneous tabs.

## Measurement

Invitation events are `mcp analytics feedback prompt shown`, `mcp analytics feedback prompt clicked`, and `mcp analytics feedback prompt dismissed`.
These measure the invitation, not the survey popover.
The SDK owns the survey lifecycle events, including `survey sent`.

Contextual survey responses carry `feedback_entry_point: session_review_prompt`, `feedback_surface: mcp_analytics`, and `mcp_analytics_tab: sessions`.
Header responses carry `feedback_entry_point: header` and the active tab.
No session IDs, tool inputs, outputs, or customer end-user details are attached by this invitation.

Use unique viewers as the denominator for invitation click rate.
Compare survey submissions by entry point over the same period, distinguishing partial from completed responses.
Do not interpret a missing survey-impression event as a zero response rate.
Reported findings or changes are qualitative evidence; invitation clicks and continued usage do not establish customer outcomes.
