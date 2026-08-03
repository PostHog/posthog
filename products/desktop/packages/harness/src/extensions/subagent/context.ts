/**
 * Builds the context a child subagent process receives beyond its bare task
 * string. Two sources, both explicit and auditable rather than a raw session
 * dump:
 *
 *  - `explicitContext`: whatever the orchestrating LLM chose to pass in the
 *    tool call's `context` field. This is the primary mechanism — the skill
 *    (see `skills/subagent-orchestration/SKILL.md`) instructs the parent to
 *    fill this in with whatever the child actually needs (file paths already
 *    found, decisions already made, constraints).
 *  - `buildAutoContext`: a small, capped digest of the last few *text-only*
 *    parent turns (no tool calls/results, no huge payloads), used only as a
 *    fallback when the caller didn't pass explicit context. This mirrors
 *    "forked context filtering" without forwarding the raw session tree.
 */
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";

const DEFAULT_MAX_AUTO_CONTEXT_CHARS = 4000;
const DEFAULT_MAX_AUTO_CONTEXT_MESSAGES = 6;

interface MinimalMessage {
  role: string;
  content?: Array<{ type: string; text?: string }>;
}

interface MinimalSessionEntry {
  type: string;
  message?: MinimalMessage;
}

function textOf(message: MinimalMessage): string {
  return (message.content ?? [])
    .filter((part) => part.type === "text" && part.text)
    .map((part) => part.text as string)
    .join("\n")
    .trim();
}

/**
 * Extracts the last few user/assistant text turns from the parent session,
 * oldest first, capped to `maxMessages` turns and `maxChars` total. Returns
 * an empty string when there's nothing usable (fresh session, tool-only
 * turns, etc.) — callers should treat that as "no auto context available".
 */
export function buildAutoContext(
  ctx: Pick<ExtensionContext, "sessionManager">,
  options: { maxMessages?: number; maxChars?: number } = {},
): string {
  const maxMessages = options.maxMessages ?? DEFAULT_MAX_AUTO_CONTEXT_MESSAGES;
  const maxChars = options.maxChars ?? DEFAULT_MAX_AUTO_CONTEXT_CHARS;

  const branch =
    ctx.sessionManager.getBranch() as unknown as MinimalSessionEntry[];
  const turns: string[] = [];

  for (let i = branch.length - 1; i >= 0 && turns.length < maxMessages; i--) {
    const entry = branch[i];
    if (entry.type !== "message" || !entry.message) continue;
    const { role } = entry.message;
    if (role !== "user" && role !== "assistant") continue;

    const text = textOf(entry.message);
    if (!text) continue;
    turns.push(`${role === "user" ? "User" : "Assistant"}: ${text}`);
  }

  turns.reverse();
  const digest = turns.join("\n\n");
  if (!digest) return "";

  if (digest.length <= maxChars) return digest;
  // Keeps the tail (most recent turns) and drops the head (earliest ones), so
  // the omission notice belongs at the *start* of what's returned — it
  // explains why the digest picks up mid-conversation, not that something
  // was cut off after the shown text.
  return `[earlier context truncated]\n\n${digest.slice(digest.length - maxChars)}`;
}

/**
 * Resolves the final context string to send to a child: explicit context
 * wins verbatim; otherwise falls back to `buildAutoContext`. Returns an
 * empty string (not undefined) when there's nothing to forward, so callers
 * can just check truthiness.
 */
export function resolveContext(
  ctx: Pick<ExtensionContext, "sessionManager">,
  explicitContext: string | undefined,
): string {
  if (explicitContext?.trim()) return explicitContext.trim();
  return buildAutoContext(ctx);
}

export function composeTaskWithContext(task: string, context: string): string {
  if (!context) return `Task: ${task}`;
  return `Task: ${task}\n\nContext from the orchestrating session:\n${context}`;
}
