# MCP analytics session feedback

The session detail panel offers an inline API survey after 30 seconds with loaded, nonempty tool calls.
Changing sessions, leaving the panel, or hiding the browser tab cancels the delay.
A visible tab starts a fresh delay.
Loading, empty, impersonated, and capture-disabled sessions do not receive a prompt.
The SDK must load the survey and its feature flags and return it as an active matching survey before the delay starts.

A separate API survey supplies stable question IDs, wording, and the question layout.
`MCPAnalyticsFeedbackPromptConfig.surveyId` selects a survey; omitting it uses the session usefulness survey.
The supported shape is a two-point emoji rating followed by one to four open-text, rating, single-choice, or multiple-choice questions.
Follow-ups can be required or optional.
Branching, custom validation, open-ended choices, shuffled choices, and link questions suppress the prompt because this pilot does not implement those behaviors.
The UI renders the survey definition using LemonUI components.
Placements can override the first two question texts through `MCPAnalyticsFeedbackPromptConfig`; the session placement uses the survey's wording.
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
Keep question IDs stable when editing wording or reordering follow-ups.
The first question must remain the two-point emoji rating.
An open prompt snapshots the full definition so edits apply to subsequent prompts.
Placements can change the wording while asking about the same usefulness measurement.
Use a new survey for a different measurement.
An unsupported question count, type, or behavior suppresses the prompt.

## Measurement

| Event              | Trigger                                      | Response fields                                                              |
| ------------------ | -------------------------------------------- | ---------------------------------------------------------------------------- |
| `survey shown`     | The inline question becomes visible          | Survey ID, name, and submission ID                                           |
| `survey sent`      | The first choice is selected                 | Question-ID response, question text snapshot, submission ID, completed false |
| `survey sent`      | Send feedback is selected                    | Same submission ID and first answer, follow-up answers, completed true       |
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
| `feedback_followup_question` | Exact first follow-up question shown                         |

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
The prompt attaches counts of visible tool calls and visible errors at the time it opens.
These counts describe the reviewed content, not the respondent’s intent or success.
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

## Voice pilot

Voice is optional input for the first open-text follow-up.
The respondent records locally for up to one minute, stops, and selects Transcribe recording to upload.
The transcript is appended to any existing answer and remains editable before the respondent selects Send feedback.
Recording, upload, and transcription never submit a survey response automatically.
Discarding, closing the prompt, or navigating away releases the microphone and any local audio URL.
A failed transcription keeps the recording available for retry; typing remains available after discarding it.

The authenticated `POST /api/projects/{project_id}/mcp_analytics/feedback_audio/` endpoint accepts a multipart `audio` file in WebM, MP4, or Ogg format, capped at 5 MiB.
It requires project access, the `mcp-analytics-feedback-voice` flag, and the organization's AI data processing approval.
The endpoint allows five requests per user per minute and uses the configured OpenAI endpoint with `gpt-4o-mini-transcribe`, a 30-second timeout, and no automatic retries.
Audio transcription is a documented [Go gateway parity gap](../../services/llm-gateway/PARITY.md).
This pilot uses the provider client until the Go gateway supports transcription; it adds no Python gateway features.
PostHog does not persist audio, the unreviewed transcript, or provider error details.
The model provider's data handling follows the deployment's provider agreement.
The reviewed text is sent only through the normal survey response event.
This authenticated pilot endpoint is for the PostHog app; it is not a public SDK upload API.

All survey lifecycle events snapshot `feedback_voice_variant` (`voice` or `text`) and `feedback_voice_available` when the prompt appears.
The boolean flag defines assignment; availability also requires browser recording support.
Completed responses include `feedback_input_method` and `feedback_voice_question_ids` to identify answers that used transcription, including transcripts edited before submission.
Do not interpret `feedback_input_method: text` on a rating-only partial response as an open-text answer.

`sessionRecordingUrl` links to the respondent's browser session near the moment the prompt appeared.
The SDK also supplies its normal session properties.
The URL does not guarantee that replay was captured or retained.
The respondent's browser replay is separate from the MCP session they were reviewing; this pilot does not copy or upload the reviewed session.

### Rollout and comparison

1. Deploy and verify the endpoint and UI with the voice flag disabled for general traffic.
   Keep the header survey in its existing popover configuration until that deployment is confirmed.
2. Enable voice for a small internal cohort with AI processing approval and confirm a real recording can be transcribed and edited.
3. Configure the same API survey for both groups.
   Keep the existing rating and open-text question IDs.
   Suggested open-text wording: "What were you trying to find, and what happened?"
   Add an optional single-choice outcome question: "Did you find what you needed?" with "Yes", "Partly", and "No".
4. Assign 50% of eligible viewers to the boolean voice flag with stable person-level assignment.
   Keep targeting, prompt delay, cooldown, and wording identical between groups.
   Record the rollout start and survey question version; exclude older submissions from the comparison.
5. Compare groups by assignment, including people offered voice who chose to type.
   Comparing voice users against typists alone is self-selected and does not estimate the effect of offering voice.

The primary measure is actionable explanations per unique shown submission.
Review a sample without exposing input method to the reviewer, using a fixed rubric: does the answer state a concrete goal, describe what happened, and provide enough detail to identify a next action?
Also report nonempty follow-up rate, completed-submission rate, dismissals, and unique viewers and organizations.
Deduplicate partial and completed events by `$survey_submission_id`.
Break results down by `feedback_voice_available` and report uncertainty when the sample is small.
Longer answers alone are not evidence of better feedback.
Keep respondent-reported outcomes separate from the usefulness rating and any inferred outcome.
