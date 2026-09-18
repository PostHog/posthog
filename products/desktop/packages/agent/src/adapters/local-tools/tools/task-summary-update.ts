import { z } from "zod";
import {
  createSandboxPosthogClient,
  withReportDeadline,
} from "../../../signed-commit-artefacts";
import { TASK_SUMMARY_MAX_CHARS } from "../../../task-summary";
import { defineLocalTool, type LocalToolResult } from "../registry";

function errorResult(message: string): LocalToolResult {
  return { content: [{ type: "text", text: message }], isError: true };
}

export const taskSummaryUpdateTool = defineLocalTool({
  name: "task_summary_update",
  description:
    "Replace this task's running summary. Write the goal, reason, current state, important files, branch, pull request, stopped approaches, and required human action. " +
    `The limit is ${TASK_SUMMARY_MAX_CHARS} characters. Each call replaces the prior summary.`,
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
    meta?.environment === "cloud" &&
    meta.taskSummarySupported === true &&
    !!ctx.taskId &&
    !!ctx.taskRunId,
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
          client.setTaskRunSummary(
            ctx.taskId as string,
            ctx.taskRunId as string,
            summary,
            signal,
          ),
        "task summary update",
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return errorResult(
        `The summary was not saved. Correct it and call task_summary_update again. Server response: ${message}`,
      );
    }
    return {
      content: [
        {
          type: "text",
          text: "Summary saved. Replace it when the goal or task state changes.",
        },
      ],
    };
  },
});
