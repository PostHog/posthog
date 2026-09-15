# MCP analytics session feedback

The session detail panel offers an inline API survey after 30 seconds with loaded, nonempty tool calls.
Changing sessions, leaving the panel, or hiding the browser tab cancels the delay.
A visible tab starts a fresh delay.
Loading, empty, impersonated, and capture-disabled sessions do not receive a prompt.
The SDK must load the survey and its feature flags and return it as an active matching survey before the delay starts.

A separate API survey supplies stable question IDs and validates the layout.
Each placement supplies its own question text through `MCPAnalyticsFeedbackPromptConfig`.
The supported shape is one two-point emoji rating question followed by one optional open-text question.
The UI renders the configured text and thumbs buttons using LemonUI components.
The prompt snapshots its copy and placement when shown, so all events in one submission describe the same displayed questions.
The first choice queues a partial response immediately and reveals the optional follow-up.
Selecting Done or Send feedback completes the same submission.
Closing or navigating away after the first answer leaves that answer available as a partial response.
A failed capture keeps the current answer and text available for retry.
The confirmation means the SDK accepted the event for delivery, not that the server acknowledged receipt.

A prompt starts a 30-day cooldown for that signed-in user in the browser, including when dismissed or left unanswered.
The header button remains available during the cooldown and opens the existing general feedback survey through the SDK's selector listener.
All placements share the same cooldown.
The cooldown uses local storage; it does not follow the user across browsers or coordinate simultaneous tabs.

## Configuration and release

Deploy the frontend with `#mcp-analytics-feedback-button` before changing the existing header survey.
Keep the current popover configuration until that deployment is confirmed.
Then configure the existing header survey as a Feedback button (`widget`) survey with an Always schedule.
Select an existing element with `appearance.widgetType: selector` and `appearance.widgetSelector: #mcp-analytics-feedback-button`.
Set URL targeting to contain `/mcp-analytics` instead of the programmatic-only placeholder URL.
Keep the survey ID and question IDs unchanged to preserve response history.
Activate the selector configuration immediately after deployment, then verify that the header button opens the survey and records its lifecycle events.
The SDK owns the click listener and captures `survey shown`, `survey sent`, and `survey dismissed`.
Do not add a second `displaySurvey` click handler or capture duplicate lifecycle events.

Create the API survey in draft with partial responses enabled and an Always schedule.
The questions are:

1. Did this session help you find what you needed? Native rating question with emoji display and a two-point scale.
2. What did you learn, or what was missing? Optional open text.

The ID in `MCP_ANALYTICS_USEFULNESS_SURVEY_ID` selects this survey.
The API survey can launch before deployment because it does not display itself.
The custom frontend must be deployed before viewers can see the prompt.
Draft and stopped surveys do not start a new prompt; a viewer with an already visible prompt can finish it.
Feature flag targeting is checked through `getActiveMatchingSurveys`, while the frontend owns the reading delay and cooldown.
Keep the question IDs, types, and order stable.
Placements can change the wording while asking about the same usefulness measurement.
Use a new survey for a different measurement.
An incompatible question count or type suppresses the prompt.

## Measurement

| Event              | Trigger                                      | Response fields                                                              |
| ------------------ | -------------------------------------------- | ---------------------------------------------------------------------------- |
| `survey shown`     | The inline question becomes visible          | Survey ID, name, and submission ID                                           |
| `survey sent`      | The first choice is selected                 | Question-ID response, question text snapshot, submission ID, completed false |
| `survey sent`      | Done or Send feedback is selected            | Same submission ID and first answer, optional text, completed true           |
| `survey dismissed` | The question or optional follow-up is closed | Same submission ID and whether the first answer was recorded                 |

The rating uses the native survey values as strings: `"1"` for thumbs up and `"2"` for thumbs down.
The properties use the standard survey schema: `$survey_id`, `$survey_name`, `$survey_submission_id`, `$survey_questions`, `$survey_response_<question-id>`, `$survey_completed`, and `$survey_partially_completed`.
Closing the thank-you state does not emit a dismissal.
Repeated answer or completion clicks do not queue another response.
These existing event names need no new event-definition registration.
Do not send synthetic events to initialize production reporting.

All inline events carry `feedback_surface: mcp_analytics` and these placement properties:

| Property                     | Value                                                        |
| ---------------------------- | ------------------------------------------------------------ |
| `feedback_entry_point`       | Stable placement identifier, such as `session_review_prompt` |
| `mcp_analytics_tab`          | Tab that contains the prompt, such as `sessions`             |
| `feedback_question_version`  | Copy version for that placement                              |
| `feedback_question`          | Exact thumbs question shown                                  |
| `feedback_followup_question` | Configured optional follow-up text                           |

`$survey_questions` pairs those displayed texts with the API survey's stable question IDs on all lifecycle events.
The API survey's configured title remains the heading in the standard results table.
Break reporting down by placement and copy version to compare contextual questions.

To reuse the prompt, pass a `prompt` configuration and a `contextKey` for the reviewed item.
The context key isolates local state when changing items and is never captured.
Keep `entryPoint` stable and increment `version` when changing either question's wording.
`MCP_ANALYTICS_SESSION_FEEDBACK_PROMPT` configures the session detail placement.
Other placements must mount the same component only when their content is ready for review.
Identify header feedback by its separate survey ID and use the SDK's `$pathname` or `$current_url` to determine the tab.
The selector widget does not receive the inline prompt's custom placement properties.
No MCP session IDs, tool inputs, outputs, or customer end-user details are attached by this prompt.
The SDK's existing viewer identity and group context remain available for cohort analysis.

Filter reporting to this survey ID and use distinct submission IDs for response rate: submissions with a first answer divided by shown submissions.
Do not count both the partial and completed events as separate responses.
Report thumbs up (`1`) and thumbs down (`2`) separately, including partial submissions with a first answer.
For adoption analysis, also report unique responding viewers and organizations rather than treating repeat responses as independent customers.
Do not interpret a missing impression event as a zero response rate.

This question measures reported usefulness of a session review.
It does not establish that the viewer changed their product or achieved a business outcome.
Assess those separately through follow-up conversations about the change made and the result observed.
