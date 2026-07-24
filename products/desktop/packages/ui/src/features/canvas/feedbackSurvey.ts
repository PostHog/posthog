// PostHog survey backing the Channels "Leave feedback" modal. Created via the
// MCP in project 2 ("PostHog App + Website") and launched so it collects
// responses. Responses are sent client-side as a `survey sent` event and only
// attach to this survey if the app reports to the same project.
// https://us.posthog.com/project/2/surveys/019ee235-2e3b-0000-64b3-5f2efa487452
export const FEEDBACK_SURVEY_ID = "019ee235-2e3b-0000-64b3-5f2efa487452";

// Open-text question: "How's the Channels experience? What would you change?".
export const FEEDBACK_SURVEY_QUESTION_ID =
  "68648b23-caaf-4080-ae5f-051513d3097f";

// Single-choice question recording where the feedback was submitted from. The
// submitted response string must match one of the survey's choices exactly —
// see FEEDBACK_SOURCE_BY_MODE.
export const FEEDBACK_SURVEY_SOURCE_QUESTION_ID =
  "e4560a6b-3eab-4c61-a731-8d0c10dd1b7d";

// Maps the modal's open reason to the source question's choice label. Values
// MUST stay in sync with the survey's single_choice options.
export const FEEDBACK_SOURCE_BY_MODE = {
  feedback: "Generic (Leave feedback button)",
  "posthog-web": "Visiting PostHog web",
} as const;
