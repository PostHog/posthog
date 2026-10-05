# API survey form foundation

The Surveys product owns a headless `apiSurveyLogic`, a reference `APISurveyForm`, and controlled `APISurveyQuestion` inputs under `products/surveys/frontend/api-surveys/`.
Only Storybook mounts these components in this change.
No product screen, survey configuration, feature flag, or rollout changes.

## Contract

Pass `surveyId` and a distinct `instanceId` for each form lifetime.
The logic loads the survey by ID from the browser SDK's `getSurveys` result.
It does not introduce a management API request or expose a personal API key.
The initialized SDK must have surveys enabled; its existing fetch and caching behavior applies.
Loading a form or feedback control emits `survey shown`; mount it only when it is visible and the caller has decided the respondent is eligible.
Targeting, launch conditions, trigger timing, cooldowns, and placement remain the caller's responsibility.

Supported questions are open text, single choice, multiple choice, numeric ratings, and two-point emoji ratings.
Every question must have a unique nonempty ID.
The form rejects branching, custom validation, links, open choices, shuffled choices, duplicate choices, and other emoji scales.
Unsupported schemas show a message instead of silently collecting incorrect answers.
Open text has a 2,000-character limit.

The question definition and caller-supplied context are copied when the survey loads.
Edits in PostHog do not change an answer already in progress.
Answers and `$survey_questions` use stable question IDs.
One complete `survey sent` event contains all nonempty answers and the original submission ID.
`APISurveyFeedback` generates one ID for its mounted lifetime unless `submissionId` is supplied.
When composing the controlled buttons and form yourself, create one unique `submissionId` in the caller and pass it to both `SurveyFeedbackButtons` and `APISurveyForm`.
Use the ID received by the button callbacks as `$survey_submission_id` when capturing the quick rating, with the same `$survey_id` as the detailed form.
Keep that ID across dialog reopenings and retries; create a new one only for a new feedback interaction.
The SDK uses the same ID across partial responses, and Surveys merges their answers by question ID.
A standalone form generates its own ID when no `submissionId` is supplied.
An unsuccessful SDK queue operation leaves answers available for retry.
Queue success does not confirm ingestion.
The rating-first flow sends the initial rating as a partial response only when `enable_partial_responses` is enabled.
Otherwise it retains the rating until the detailed response is submitted.
A survey with just one rating question completes immediately.
The foundation does not manage SDK seen/responded storage, reload feature flags, or emit automatic dismissal events.

## Feedback controls

`APISurveyFeedback` loads the API survey before showing its first rating question.
It owns one mounted logic instance for the rating and the dialog, preserving answers and the submission ID across dialog reopenings.
The dialog renders the remaining questions, and the final response includes the initial rating.

`SurveyFeedbackButtons` is the controlled rating input with a separate Share more feedback action.
Its question prop supplies the prompt, description, scale, and endpoint labels.
Two-point emoji ratings use thumbs; numeric ratings use the configured range, including 0 through 10.
It calls `onChange(rating, submissionId)` immediately with the selected value (`1` for thumbs up or `2` for thumbs down).
After the caller accepts a rating, the rating buttons are replaced by Share more feedback, which calls `onMoreFeedback(submissionId)`.
When using the controlled buttons alone, the caller owns persistence, pending and error state, and the link between the rating and details.
Pass `loading` while saving to prevent duplicate actions, and update `value` when the caller accepts the rating.
The prompt and action sit at opposite ends of the row.
Share more feedback replaces the rating buttons after a rating is accepted, with a short fade that respects reduced-motion preferences.
After a user selects a rating, focus moves to that action once saving finishes and the action is enabled.
A preselected rating does not take focus on mount.
The component does not load a survey or emit analytics events itself.

Inside the form, ratings and up to four short single-choice options use compact selectable buttons with native radio inputs.
Short multiple-choice lists use bordered checkboxes that wrap onto another row when needed.
Long labels and larger choice lists keep the vertical layout.

## Keyboard navigation

Shortcuts only act on a focused answer inside the form.
Arrow keys select radio choices and ratings, and move between checkboxes without toggling them.
Space toggles the focused checkbox.
Enter moves to the next question; in text answers, Ctrl/Cmd + Enter does the same while plain Enter inserts a newline.
After the last question, focus moves to the enabled Send feedback button, which Enter or Space activates.
Tab and Shift+Tab keep their normal browser behavior, including leaving the survey.
Mounting or loading a survey does not steal focus.

## Context and replay

The optional `context` object is captured on the shown and sent events.
Callers should supply only the context they intend to collect, such as placement, task category, or experiment assignment.
Reserved survey identity and response properties cannot be overridden by context.
`includeReplay` explicitly includes `sessionRecordingUrl` for the respondent's current browser session.
The URL does not guarantee that a recording exists or remains retained.
Replay is off by default.

## Stories and future integration

`Surveys/API survey form` covers the reference form, unavailable and loading states, and request failures.
`Surveys/API survey question` covers each supported control.
Stories inject a client that uses invented surveys and never sends analytics events.
The Dialog and NumericRating stories use `APISurveyFeedback` with an invented survey and a fake capture client.
They exercise the rating-first flow, including partial responses, without sending live events.
FeedbackLoading and FeedbackUnavailable show the states before a rating can be offered.
The form mounts only while the dialog is open, and Escape or the close button returns focus to the trigger.
Backdrop clicks leave the dialog open to avoid losing input accidentally.
Closing retains the detail draft and submission ID for the lifetime of the feedback component.
This placement is a Storybook prototype, with product integration still owned by callers.
Product-specific context capture and response-quality experiments belong in later integrations.
Voice recording and transcription are a separate foundation change.
