import { z } from "zod";

export interface RunPolicy {
  readonly finishTool: boolean;
  /** A workflow run that opts into `finish` hands its report to the next step. */
  readonly finishReportRequired: boolean;
  readonly reportActivityTool: boolean;
  readonly expectsSystemPrompt: boolean;
  readonly threadLink: boolean;
  readonly defaultClientProvenance: string | undefined;
}

export interface RunPolicyInput {
  readonly originProduct: string | null | undefined;
  readonly endRunWhenDone: boolean;
  readonly callerEndsRun: boolean;
}

const serverRunPolicySchema = z.object({
  finish_tool: z.boolean(),
  finish_report_required: z.boolean(),
  report_activity_tool: z.boolean(),
  expects_system_prompt: z.boolean(),
  thread_link: z.boolean(),
  default_client_provenance: z.string().nullable(),
});

export function parseServerRunPolicy(raw: string): RunPolicy | undefined {
  let payload: unknown;
  try {
    payload = JSON.parse(raw);
  } catch {
    return undefined;
  }
  const parsed = serverRunPolicySchema.safeParse(payload);
  if (!parsed.success) {
    return undefined;
  }
  return {
    finishTool: parsed.data.finish_tool,
    finishReportRequired: parsed.data.finish_report_required,
    reportActivityTool: parsed.data.report_activity_tool,
    expectsSystemPrompt: parsed.data.expects_system_prompt,
    threadLink: parsed.data.thread_link,
    defaultClientProvenance: parsed.data.default_client_provenance ?? undefined,
  };
}

const CALLER_ENDS_RUN_ORIGINS = new Set(["review_hog", "scout_suggestions"]);

// Automated origins get no thread link, so sibling tasks keep one shared prompt cache.
const THREAD_ORIGINS = new Set(["user_created", "posthog_ai"]);

export function runPolicyFromOrigin({
  originProduct,
  endRunWhenDone,
  callerEndsRun,
}: RunPolicyInput): RunPolicy {
  const origin = originProduct ?? "";
  const originKnown = origin !== "";
  const workflow = origin === "workflow";
  const posthogAi = origin === "posthog_ai";

  return {
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
    // ReviewHog and suggestions callers own completion. An agent-side finish can
    // interrupt structured output, follow-up turns, or persistence.
    finishTool:
      !callerEndsRun &&
      !CALLER_ENDS_RUN_ORIGINS.has(origin) &&
      ((originKnown && !workflow) || endRunWhenDone),
    finishReportRequired: workflow && endRunWhenDone,
    reportActivityTool: origin === "task_analysis",
    expectsSystemPrompt: posthogAi,
    threadLink: THREAD_ORIGINS.has(origin),
    // Browser session auth records no provenance, so a posthog_ai task without one comes from the web.
    defaultClientProvenance: posthogAi ? "posthog_web" : undefined,
  };
}
