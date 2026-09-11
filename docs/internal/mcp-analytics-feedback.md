# MCP analytics session feedback

The session detail panel offers an inline API survey after 30 seconds with loaded, nonempty tool calls.
Changing sessions, leaving the panel, or hiding the browser tab cancels the delay.
A visible tab starts a fresh delay.
Loading, empty, impersonated, and capture-disabled sessions do not receive a prompt.
The SDK must load the survey and its feature flags and return it as an active matching survey before the delay starts.

The question and choices come from a separate API survey, rather than the generic header feedback survey.
The supported shape is one two-point emoji rating question followed by one optional open-text question.
The UI renders the question text and thumbs buttons using LemonUI components.
The first choice queues a partial response immediately and reveals the optional follow-up.
Selecting Done or Send feedback completes the same submission.
Closing or navigating away after the first answer leaves that answer available as a partial response.
A failed capture keeps the current answer and text available for retry.
The confirmation means the SDK accepted the event for delivery, not that the server acknowledged receipt.

A prompt starts a 30-day cooldown for that signed-in user in the browser, including when dismissed or left unanswered.
The header button remains available during the cooldown and opens the existing general feedback popover.
The cooldown uses local storage; it does not follow the user across browsers or coordinate simultaneous tabs.

## Configuration and release

Create the API survey in draft with partial responses enabled and an Always schedule.
The questions are:

1. Did this session help you find what you needed? Native rating question with emoji display and a two-point scale.
2. What did you learn, or what was missing? Optional open text.

The ID in `MCP_ANALYTICS_USEFULNESS_SURVEY_ID` selects this survey.
Deploy the frontend before launching the survey.
Draft and stopped surveys do not start a new prompt; a viewer with an already visible prompt can finish it.
Feature flag targeting is checked through `getActiveMatchingSurveys`, while the frontend owns the reading delay and cooldown.
Keep the question types, order, and meaning stable; use a new survey for a different measurement.
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

All inline events carry `feedback_entry_point: session_review_prompt`, `feedback_surface: mcp_analytics`, and `mcp_analytics_tab: sessions`.
Header responses carry `feedback_entry_point: header` and the active tab.
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
