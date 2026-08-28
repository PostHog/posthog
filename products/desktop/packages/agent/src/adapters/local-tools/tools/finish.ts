import { z } from "zod";
import {
  createSandboxPosthogClient,
  withReportDeadline,
} from "../../../signed-commit-artefacts";
import {
  defineLocalTool,
  type LocalToolCtx,
  type LocalToolResult,
} from "../registry";

export const FINISH_TOOL_NAME = "finish";

export const finishSchema = {
  status: z
    .enum(["completed", "failed"])
    .default("completed")
    .describe(
      "How the run ended. 'completed' (default) for a normal, successful " +
        "finish; 'failed' only if you hit something you could not get past and " +
        "are stopping short of the goal.",
    ),
  reason: z
    .string()
    .max(500)
    .optional()
    .describe(
      "Short note on why you're stopping — recorded on the run. Required-in- " +
        "spirit for 'failed': say what blocked you so a human can pick it up.",
    ),
};

export const FINISH_TOOL_DESCRIPTION =
  "End this run and release the sandbox. This is an unattended background run: " +
  "nothing else will stop it promptly, so calling `finish` is how the machine " +
  "is reclaimed instead of sitting idle until a timeout fires. Call it once — " +
  "and only once — you are genuinely done: every sub-agent has returned, any CI " +
  "or checks you were waiting on have settled, and you've delivered whatever " +
  "your instructions asked for (or deliberately skipped delivery per those " +
  "instructions). Do NOT call it while you're still working or still waiting on " +
  "something to finish. After it returns, stop — the run is over.";

/**
 * Lets the model end its own background run. The handler calls back into the
 * adapter's `requestFinish`, which marks the task run terminal via the PostHog
 * API; the Temporal workflow observes the terminal status and tears the sandbox
 * down. Gated to cloud runs that actually own a sandbox — local sessions have
 * no `requestFinish` and no sandbox to reclaim, so the tool stays hidden there.
 */
// Adapters that run local tools in a separate process (codex) cannot pass the
// in-process `requestFinish` callback through the serialized tool context, so
// the tool falls back to the same PostHog API PATCH that callback performs.
function resolveRequestFinish(
  ctx: LocalToolCtx,
): LocalToolCtx["requestFinish"] {
  if (ctx.requestFinish) {
    return ctx.requestFinish;
  }
  const { taskId, taskRunId } = ctx;
  if (!taskId || !taskRunId) {
    return undefined;
  }
  const client = createSandboxPosthogClient();
  if (!client) {
    return undefined;
  }
  return async (status, message) => {
    await withReportDeadline(
      (signal) =>
        client.updateTaskRun(
          taskId,
          taskRunId,
          {
            status,
            ...(status === "failed" && message
              ? { error_message: message }
              : {}),
          },
          signal,
        ),
      "run finish",
    );
  };
}

export const finishTool = defineLocalTool({
  name: FINISH_TOOL_NAME,
  description: FINISH_TOOL_DESCRIPTION,
  schema: finishSchema,
  alwaysLoad: true,
  // Workflow-origin runs are excluded unless run state carries the end-run
  // key: they reply into the Slack thread that triggered them, and that relay
  // only fires after the turn ends. `finish` marks the run terminal mid-turn,
  // which makes the backend drop the relay (relay_task_run_message skips
  // terminal runs), so the reply is lost every time. Without the key those
  // runs end via their inactivity timeout instead. The backend writes the key
  // for every workflow run with no Slack thread binding, so only thread-bound
  // runs pay the timeout. An unknown origin also hides the tool: the origin
  // fetch fails soft, and exposing `finish` on a blip would silently eat a
  // workflow run's reply, while hiding it only costs a bounded idle window.
  isEnabled: (ctx, meta) =>
    meta?.environment === "cloud" &&
    meta?.background === true &&
    ((meta?.taskOriginProduct !== undefined &&
      meta?.taskOriginProduct !== "workflow") ||
      meta?.endRunWhenDone === true) &&
    resolveRequestFinish(ctx) !== undefined,
  handler: async (ctx, args): Promise<LocalToolResult> => {
    const requestFinish = resolveRequestFinish(ctx);
    if (!requestFinish) {
      return {
        content: [
          { type: "text", text: "finish is not available in this session." },
        ],
        isError: true,
      };
    }
    await requestFinish(args.status, args.reason);
    return {
      content: [
        {
          type: "text",
          text: `Run marked ${args.status}; shutting the sandbox down. Stop here.`,
        },
      ],
    };
  },
});
