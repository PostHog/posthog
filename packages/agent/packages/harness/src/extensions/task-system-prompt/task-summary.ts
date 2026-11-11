export const TASK_SUMMARY_TOOL_NAME = "task_summary_update";

// Matches the server-side limit on the set_summary endpoint.
export const TASK_SUMMARY_MAX_CHARS = 1500;
export const TASK_TAGS_MAX_COUNT = 10;
export const TASK_TAG_MAX_CHARS = 50;
export const TASK_TAG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

export function buildTaskSummaryInstructions(): string {
  return `## Keeping the task summary
Call the \`${TASK_SUMMARY_TOOL_NAME}\` tool when the goal changes, when you stop one approach, about every ten turns, and before you end any turn. A turn that only answers a question counts. Each call replaces the prior summary. Write the current state and remove details that no longer matter. Keep the summary to a few sentences.

Also send \`tags\`: up to ${TASK_TAGS_MAX_COUNT} lowercase kebab-case slugs that name the product area and the kind of work, for example \`feature-flags\` or \`bug-fix\`. Each call replaces the prior tags. Omit \`tags\` to keep the current tags.`;
}
