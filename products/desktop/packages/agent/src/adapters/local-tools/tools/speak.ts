import { z } from "zod";
import { defineLocalTool, type LocalToolResult } from "../registry";

export const SPEAK_TOOL_NAME = "speak";

export const speakSchema = {
  text: z
    .string()
    .min(1)
    .max(400)
    .describe(
      "The message to say out loud — just the content, one short sentence. Do " +
        "NOT add a task-name prefix or the user's name yourself; the app " +
        "prepends the current task (\"PostHog task '…' —\") and, for " +
        "needsUser lines, addresses the user by their real name automatically. " +
        'So say e.g. "moving on to search the database" or "I need your call ' +
        'on which branch to use". Use expressive audio tags in [square ' +
        "brackets] like [laughs], [sighs], [excited]; they are stripped " +
        "automatically by the system-voice fallback.",
    ),
  kind: z
    .enum(["needs_input", "done", "progress"])
    .describe(
      "Why you're speaking. 'needs_input': you're blocked and need the user " +
        "(a question, decision, confirmation, or an error only they can " +
        'resolve) — highest priority, spoken as "Hey <name>, …", never ' +
        "dropped. 'done': you've finished the user's request. 'progress': " +
        "you've moved to a meaningful new phase. The user controls which of " +
        "these are spoken and may mute 'progress' entirely, so reserve it for " +
        "genuine phase changes — never routine steps.",
    ),
};

export const SPEAK_TOOL_DESCRIPTION =
  "Say a short line out loud to the user via text-to-speech — how you hand " +
  "them information while they look at another window. Lean toward using it. " +
  "Call it when you are BLOCKED and need them (kind 'needs_input'); when you " +
  "FINISH their request (kind 'done') — and there, say the actual RESULT or " +
  "answer, not just that you're done; and when you learn something they'd want " +
  "to hear mid-task (kind 'progress') — a notable finding or number. Don't " +
  "narrate routine steps or every file edit, but don't hoard useful results " +
  "either. Playback is best-effort and serialized across all running agents; " +
  "this tool returns immediately and never blocks your work.";

/**
 * A no-op-on-the-agent-side narration tool. The handler runs inside the agent
 * process (local subprocess or cloud sandbox) which cannot reach the user's
 * speakers, so it just acknowledges. The desktop renderer observes the
 * surfaced `tool_call` (carrying `text`/`needsUser` in its rawInput) and routes
 * it to the speech queue, exactly like completion/permission notifications are
 * pure side effects off the event stream. Gated on `spokenNarration`, which is
 * strictly opt-in (see `resolveSpokenNarration`): the desktop passes it true
 * only when the feature flag and the user's setting are both enabled. Headless
 * cloud runs (Slack threads, Signals scouts) never enable it, so the tool and
 * its instructions never load and never cost tokens there.
 */
export const speakTool = defineLocalTool({
  name: SPEAK_TOOL_NAME,
  description: SPEAK_TOOL_DESCRIPTION,
  schema: speakSchema,
  alwaysLoad: true,
  isEnabled: (_ctx, meta) => meta?.spokenNarration === true,
  handler: async (): Promise<LocalToolResult> => {
    return { content: [{ type: "text", text: "ok" }] };
  },
});
