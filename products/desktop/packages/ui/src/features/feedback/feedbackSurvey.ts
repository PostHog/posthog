// PostHog survey backing the Desktop feedback modal. Created in project 2
// ("PostHog App + Website") and launched so it collects responses.
// https://us.posthog.com/project/2/surveys/019ee235-2e3b-0000-64b3-5f2efa487452
export const FEEDBACK_SURVEY_ID = "019ee235-2e3b-0000-64b3-5f2efa487452";

export const FEEDBACK_SURVEY_QUESTION_ID =
  "68648b23-caaf-4080-ae5f-051513d3097f";

// The submitted value must match one of the survey's choices exactly.
export const FEEDBACK_SURVEY_SOURCE_QUESTION_ID =
  "e4560a6b-3eab-4c61-a731-8d0c10dd1b7d";

export const FEEDBACK_SOURCE_BY_MODE = {
  feedback: "Generic (Leave feedback button)",
  "posthog-web": "Visiting PostHog web",
} as const;
