# MCP analytics session feedback

The session detail panel shows a thumbs question after 30 seconds with loaded tool calls.
Refreshing feature flags keeps an already-pending delay when the same survey remains eligible.
Leaving the panel or hiding the tab cancels the delay; returning starts a fresh delay.
The SDK must return an active matching survey, and capture must be enabled for a signed-in, non-impersonated user.
Showing the prompt starts a 30-day cooldown shared across sequential placements for that user in this browser.
Mount only one placement at a time; simultaneous placements do not synchronize their in-memory cooldowns.
Feedback is requested in context; the page header has no general Feedback button.

## Configuration and rollout

`MCP_ANALYTICS_USEFULNESS_SURVEY_ID` selects an API survey with partial responses enabled and an Always schedule.
Recurring survey iterations are not supported.
The survey belongs to the project configured for PostHog’s own analytics SDK, not the customer project being viewed.
Its questions must be a two-point emoji rating followed by optional open text, both with stable IDs.
`MCP_ANALYTICS_SESSION_FEEDBACK_PROMPT` supplies the displayed copy and placement metadata.
Incompatible, draft, stopped, or nonmatching surveys do not start a prompt.
The API survey can launch before deployment because it does not display itself.

After deployment, verify `survey shown` events before interpreting zero responses as lack of feedback.
Check the SDK project, targeting, survey status, and question schema if impressions are absent.
This change needs no update to the existing header survey configuration.

## Events and reporting

- `survey shown` records the impression and starts the cooldown.
- `survey sent` records the first answer immediately with `$survey_completed: false`.
- Done or Send feedback sends the same answer and optional text with `$survey_completed: true` and the same submission ID.
- Navigating away does not emit a dismissal or abandonment event; any partial response already captured remains.
- `survey dismissed` records an unfinished dismissal and whether the first answer was captured. Closing the thank-you state does not count.

Responses use `$survey_response_<question-id>` with `"1"` for thumbs up and `"2"` for thumbs down.
All inline events share `$survey_submission_id`, stable question IDs, and the displayed wording in `$survey_questions`.
They also carry `feedback_surface`, `feedback_entry_point`, `mcp_analytics_tab`, `feedback_question_version`, `feedback_question`, and `feedback_followup_question`.
Copy is captured when the prompt appears so it stays consistent throughout the submission.
Failed captures preserve the answer for retry; a confirmation means the SDK queued the event, not that the server received it.

Count distinct submission IDs with an answer divided by distinct shown submission IDs; do not double-count partial and completed events.
Compare placements and copy versions, and report unique viewers and organizations alongside response counts.
The prompt adds no MCP session IDs, tool inputs, outputs, or customer end-user details.
Reported usefulness does not establish a business outcome; assess that through follow-up conversations.
