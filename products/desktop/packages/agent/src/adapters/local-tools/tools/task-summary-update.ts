import { z } from "zod";
import {
  createSandboxPosthogClient,
  withReportDeadline,
} from "../../../signed-commit-artefacts";
import { defineLocalTool, type LocalToolResult } from "../registry";

/**
 * Matches the server-side cap in `validate_set_output`. The cap is the feature: a
 * summary somebody reads on hover has to fit in a hover, and the limit is what makes
 * the agent drop the parts that stopped mattering.
 */
export const TASK_SUMMARY_MAX_CHARS = 1500;

function errorResult(message: string): LocalToolResult {
  return { content: [{ type: "text", text: message }], isError: true };
}

export const taskSummaryUpdateTool = defineLocalTool({
  name: "task_summary_update",
  description:
    "Replace this task's running summary — what somebody sees when they open the task without having read the run. " +
    `Each call overwrites the whole summary, so write the current state, not a diary entry. Cap: ${TASK_SUMMARY_MAX_CHARS} characters; a longer call is rejected. ` +
    "Write it self-contained: name the repository, product, files, branches and PR URLs in full, because the reader has none of your context. " +
    "Cover what the task is trying to do, why in one line, where it stands (including routes you abandoned and why), where the work lives, and anything that needs a human. " +
    "Good: 'Adding a task_summary_update tool to posthog/posthog (tasks product) so a task says what it is about. Why: dropping into someone else's task means re-reading the whole run log. State: tool + server cap done in products/desktop/packages/agent and products/tasks/backend/facade/api.py, sidebar hover left. Dropped a Task.summary column — the issue scopes it out until adoption is known. Branch posthog/task-summary, no PR yet.' " +
    "Bad: 'Working on the summary tool. Made good progress.' — names nothing, tells the reader nothing they could act on.",
  schema: {
    summary: z
      .string()
      .min(1)
      .max(TASK_SUMMARY_MAX_CHARS)
      .describe(
        "The complete summary, replacing any previous one. Plain text or short markdown.",
      ),
  },
  alwaysLoad: true,
  isEnabled: (ctx, meta) =>
    meta?.environment === "cloud" && !!ctx.taskId && !!ctx.taskRunId,
  handler: async (ctx, args): Promise<LocalToolResult> => {
    if (!ctx.taskId || !ctx.taskRunId) {
      return errorResult("Task summaries are not available here.");
    }
    const summary = args.summary.trim();
    if (!summary) {
      return errorResult("The summary is empty.");
    }
    const client = createSandboxPosthogClient();
    if (!client) {
      return errorResult(
        "PostHog is not configured in this sandbox; the summary cannot be saved.",
      );
    }
    try {
      await withReportDeadline(
        (signal) =>
          client.setTaskRunOutput(
            ctx.taskId as string,
            ctx.taskRunId as string,
            { output: { summary } },
            signal,
          ),
        "task summary update",
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return errorResult(
        `The summary was rejected and was not saved. Shorten it and call task_summary_update again. Server response: ${message}`,
      );
    }
    return {
      content: [
        {
          type: "text",
          text: "Summary saved. Replace it again when the goal changes or the state moves on.",
        },
      ],
    };
  },
});
