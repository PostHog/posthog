# API survey form foundation

The Surveys product owns a headless `apiSurveyLogic`, a reference `APISurveyForm`, and controlled `APISurveyQuestion` inputs under `products/surveys/frontend/api-surveys/`.
Only Storybook mounts these components in this change.
No product screen, survey configuration, feature flag, or rollout changes.

## Contract

Pass `surveyId` and a distinct `instanceId` for each form lifetime.
The logic loads the survey by ID from the browser SDK's `getSurveys` result.
It does not introduce a management API request or expose a personal API key.
The initialized SDK must have surveys enabled; its existing fetch and caching behavior applies.
Loading a form emits `survey shown`; mount the form only when it is visible and the caller has decided the respondent is eligible.
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
An unsuccessful SDK queue operation leaves answers available for retry.
Queue success does not confirm ingestion.
This foundation does not submit partial answers or emit automatic dismissal events.

## Feedback controls

`SurveyFeedbackButtons` is a controlled thumbs-up/down input with a separate Share more feedback action.
It calls `onChange` immediately with `1` for helpful or `2` for not helpful; clicking the selected rating again does nothing.
The caller owns persistence, pending and error state, and any link between a quick rating and a detailed response.
Pass `loading` while saving to prevent duplicate actions, and update `value` when the caller accepts the rating.
The component does not load a survey or emit analytics events itself.

Ratings and up to four short single-choice options use compact selectable buttons with native radio inputs.
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
The Dialog story starts with SurveyFeedbackButtons and opens LemonModal only on Share more feedback; DialogOpen captures the open state.
Its quick rating stays selected when the dialog closes and is included in the detailed response context.
The story stores the rating locally; it does not demonstrate production persistence or response enrichment.
The form mounts only while the dialog is open, and Escape or the close button returns focus to the trigger.
Backdrop clicks leave the dialog open to avoid losing input accidentally.
Closing discards the draft; reopening starts a new response.
This placement is a Storybook prototype, with product integration still owned by callers.
Product-specific context capture and response-quality experiments belong in later integrations.
Voice recording and transcription are a separate foundation change.
