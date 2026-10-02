import { z } from "zod";
import { defineLocalTool, type LocalToolResult } from "../registry";
import {
  createSandboxPosthogClient,
  withReportDeadline,
} from "../signed-commit-artefacts";

const MAX_MESSAGE_LENGTH = 2000;

export const NOTIFY_USER_TOOL_NAME = "notify_user";

export const notifyUserTool = defineLocalTool({
  name: NOTIFY_USER_TOOL_NAME,
  description:
    "Send a message to the user who owns this task, outside PostHog Code. Today the only channel is a Slack DM. " +
    "Use it when the user asked you to send updates, when you are blocked and need the user to answer, " +
    "or when long work the user asked to hear about is done. Do not use it to narrate routine progress. " +
    "The recipient is always the task owner. When the result says replies continue the task, " +
    "a reply in the Slack thread reaches you as a new user message.",
  schema: {
    channel: z
      .enum(["slack"])
      .default("slack")
      .describe("Where to send the message. Only slack is available now."),
    reason: z
      .enum(["update", "needs_input", "done"])
      .describe(
        "update: progress the user asked for. needs_input: you are blocked until the user answers. done: the work is finished.",
      ),
    message: z
      .string()
      .min(1)
      .max(MAX_MESSAGE_LENGTH)
      .describe(
        "Short plain-text message. Say what happened and, for needs_input, the exact question. PostHog adds the task title and a link.",
      ),
  },
  alwaysLoad: true,
  isEnabled: (ctx, meta) =>
    meta?.environment === "cloud" &&
    !!ctx.taskId &&
    !!ctx.taskRunId &&
    meta?.notifyUser === true,
  handler: async (ctx, args): Promise<LocalToolResult> => {
    if (!ctx.taskId || !ctx.taskRunId) {
      return errorResult("Notifications are not available in this session.");
    }
    const message = args.message.trim();
    if (!message) {
      return errorResult("The message is empty.");
    }
    const client = createSandboxPosthogClient();
    if (!client) {
      return errorResult(
        "PostHog API access is not configured in this sandbox.",
      );
    }
    try {
      const result = await withReportDeadline(
        (signal) =>
          client.notifyTaskOwner(
            ctx.taskId as string,
            ctx.taskRunId as string,
            { channel: args.channel, reason: args.reason, message },
            signal,
          ),
        "user notification",
      );
      if (result.result === "sent") {
        return { content: [{ type: "text", text: result.detail }] };
      }
      return errorResult(result.detail);
    } catch (error) {
      return errorResult(
        `Sending the notification failed: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  },
});

function errorResult(message: string): LocalToolResult {
  return { content: [{ type: "text", text: message }], isError: true };
}
