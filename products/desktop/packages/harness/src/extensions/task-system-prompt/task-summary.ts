export const TASK_SUMMARY_TOOL_NAME = "task_summary_update";

// Matches the server-side limit on the set_summary endpoint.
export const TASK_SUMMARY_MAX_CHARS = 1500;

export function buildTaskSummaryInstructions(): string {
  return `## Keeping the task summary
Call the \`${TASK_SUMMARY_TOOL_NAME}\` tool when the goal changes, when you stop one approach, about every ten turns, and before you end a turn. Each call replaces the prior summary. Write the current state and remove details that no longer matter. Keep the summary to a few sentences.`;
}
