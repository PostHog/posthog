/**
 * Per-turn trace id recovery for gateway sessions.
 *
 * The LLM gateway derives each `$ai_generation`'s `$ai_trace_id` from the W3C
 * `traceparent` header the Claude CLI sends, and the CLI mints one trace id
 * per user turn. The CLI never reports that id on its stdout protocol, so the
 * agent-server cannot correlate a turn with its generations. The CLI does
 * export `TRACEPARENT` into every subprocess it spawns, hooks included, so a
 * `UserPromptSubmit` command hook can echo it. With `includeHookEvents` on,
 * the echo arrives as a `hook_response` SDK message before the turn's first
 * gateway request.
 *
 * The hook writes to stderr: a `UserPromptSubmit` hook's stdout is injected
 * into the model's context, stderr is not.
 *
 * `hook_response` carries no field identifying which settings source declared
 * a hook (`hook_name` is just the event name), so a per-session random nonce
 * in the stderr prefix keeps another `UserPromptSubmit` hook (user or repo
 * settings) from colliding with this channel by accident. It is not a
 * security boundary: the nonce rides the CLI's `--settings` argv, readable by
 * any process on the machine, and a repo hook already runs with the session's
 * full privileges.
 */

import { randomBytes } from "node:crypto";

const TRACEPARENT_STDERR_PREFIX = "traceparent:";

/** Per-session discriminator for the hook's stderr prefix. Hex only, so it is
 * safe inside the single-quoted shell command and the settings JSON. */
export function generateTraceparentHookNonce(): string {
  return randomBytes(8).toString("hex");
}

/** Value for the CLI's `--settings <json>` flag declaring the hook. */
export function buildTraceparentHookSettingsJson(nonce: string): string {
  const command = `printf '${TRACEPARENT_STDERR_PREFIX}${nonce}=%s' "$TRACEPARENT" >&2`;
  return JSON.stringify({
    hooks: {
      UserPromptSubmit: [{ hooks: [{ type: "command", command }] }],
    },
  });
}

/**
 * Parses the hook's stderr into the gateway's `$ai_trace_id` form: the
 * traceparent's 32-hex trace id rendered as a UUID, matching the gateway's
 * `str(UUID(hex=...))`. Returns null for anything else, including a
 * missing/mismatched nonce and the all-zero id the W3C spec reserves for
 * "no trace".
 */
export function traceIdFromHookStderr(
  stderr: string,
  nonce: string | undefined,
): string | null {
  if (!nonce) {
    return null;
  }
  const prefix = `${TRACEPARENT_STDERR_PREFIX}${nonce}=`;
  if (!stderr.startsWith(prefix)) {
    return null;
  }
  const traceparent = stderr.slice(prefix.length).trim();
  const match = /^[0-9a-f]{2}-([0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}$/.exec(
    traceparent,
  );
  if (!match || /^0{32}$/.test(match[1])) {
    return null;
  }
  const hex = match[1];
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
