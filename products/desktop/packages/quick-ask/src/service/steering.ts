import { RICH_OUTPUT_TAGS_PROMPT } from "@posthog/shared/rich-output-prompt";

/**
 * Sent after the user's first question, so the task title stays the question.
 * The tag vocabulary is the shared block the renderer's object-tag pipeline
 * parses.
 */
export const PANEL_STEERING = `<posthog_trusted_context>
This question was asked from PostHog Desktop's compact quick-ask panel. For this whole conversation:
- Answer from PostHog data using the PostHog MCP tools. Do not clone repositories or modify code.
- Keep the text answer short - a few sentences at most.
- Never ask a blocking question; make reasonable assumptions and state them briefly.
- Rich output: ${RICH_OUTPUT_TAGS_PROMPT}
</posthog_trusted_context>`;
