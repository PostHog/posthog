import { sleepWithBackoff } from "@posthog/agent-contracts";
import { z } from "zod";
import {
  TASK_SUMMARY_MAX_CHARS,
  TASK_SUMMARY_TOOL_NAME,
  TASK_TAG_MAX_CHARS,
  TASK_TAG_PATTERN,
  TASK_TAGS_MAX_COUNT,
} from "../../task-system-prompt/task-summary";
import { defineLocalTool, type LocalToolResult } from "../registry";
import {
  createSandboxPosthogClient,
  withReportDeadline,
} from "../signed-commit-artefacts";
import { TaskToolsApiError } from "../task-tools-client";

const SUMMARY_ATTEMPTS = 3;
const SUMMARY_ATTEMPT_TIMEOUT_MS = 10_000;
const SUMMARY_DEADLINE_MS = 30_000;
const SUMMARY_RETRY_BACKOFF = { initialDelayMs: 1_000, maxDelayMs: 4_000 };

function errorResult(message: string): LocalToolResult {
  return { content: [{ type: "text", text: message }], isError: true };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

// A 4xx other than 408 or 429 means the server read the payload and refused it, so a repeat
// fails the same way. A 5xx, a timeout, or a dropped connection can pass on a repeat, and a
// repeat is safe because each call replaces the stored summary and tags.
function isRejection(error: unknown): boolean {
  return (
    error instanceof TaskToolsApiError &&
    error.status >= 400 &&
    error.status < 500 &&
    error.status !== 408 &&
    error.status !== 429
  );
}

export const taskSummaryUpdateTool = defineLocalTool({
  name: TASK_SUMMARY_TOOL_NAME,
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
    tags: z
      .array(z.string().max(TASK_TAG_MAX_CHARS).regex(TASK_TAG_PATTERN))
      .max(TASK_TAGS_MAX_COUNT)
      .optional()
      .describe(
        "The complete set of lowercase kebab-case slugs, for example `feature-flags` or `bug-fix`, replacing any previous tags. Omit to keep the current tags.",
      ),
  },
  alwaysLoad: true,
  // The summary is stored on the cloud task run, so a local session has nowhere to write it.
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
    const deadline = Date.now() + SUMMARY_DEADLINE_MS;
    let attempts = 0;
    let lastError: unknown;
    while (attempts < SUMMARY_ATTEMPTS) {
      if (attempts > 0) {
        await sleepWithBackoff(attempts - 1, SUMMARY_RETRY_BACKOFF);
      }
      const remainingMs = deadline - Date.now();
      if (remainingMs <= 0) {
        break;
      }
      attempts += 1;
      try {
        await withReportDeadline(
          (signal) =>
            client.setTaskRunSummary(
              ctx.taskId as string,
              ctx.taskRunId as string,
              summary,
              args.tags,
              signal,
            ),
          "task summary update",
          Math.min(SUMMARY_ATTEMPT_TIMEOUT_MS, remainingMs),
        );
        return {
          content: [
            {
              type: "text",
              text: "Summary saved. Replace it when the goal or task state changes.",
            },
          ],
        };
      } catch (error) {
        if (isRejection(error)) {
          return errorResult(
            `The server rejected the summary, so it was not saved. Correct the summary or tags and call ${TASK_SUMMARY_TOOL_NAME} again. Server response: ${errorMessage(error)}`,
          );
        }
        lastError = error;
      }
    }
    return errorResult(
      `The server did not confirm the summary after ${attempts} attempts, so it may not be saved. This is a server-side failure, not a problem with your summary or tags, so do not change them. Call ${TASK_SUMMARY_TOOL_NAME} again later with the same arguments. Each call replaces the summary, so a repeat cannot store it twice. Last error: ${errorMessage(lastError)}`,
    );
  },
});
