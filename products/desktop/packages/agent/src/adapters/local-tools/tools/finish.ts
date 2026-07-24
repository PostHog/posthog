import { z } from "zod";
import { defineLocalTool, type LocalToolResult } from "../registry";

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
export const finishTool = defineLocalTool({
  name: FINISH_TOOL_NAME,
  description: FINISH_TOOL_DESCRIPTION,
  schema: finishSchema,
  alwaysLoad: true,
  isEnabled: (ctx, meta) =>
    meta?.environment === "cloud" &&
    meta?.background === true &&
    ctx.requestFinish !== undefined,
  handler: async (ctx, args): Promise<LocalToolResult> => {
    if (!ctx.requestFinish) {
      return {
        content: [
          { type: "text", text: "finish is not available in this session." },
        ],
        isError: true,
      };
    }
    await ctx.requestFinish(args.status, args.reason);
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
