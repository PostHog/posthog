const TASK_TITLE_MAX = 40;
const TASK_PREFIX = "PostHog task";
const TASK_PREFIX_GUARD = new RegExp(`^\\s*${TASK_PREFIX}`, "i");

export interface ComposeInput {
  text: string;
  taskTitle: string;
  needsUser?: boolean;
  firstName?: string;
  /** Prepend "Hey <name>," — only for agent-authored lines, not the backstop. */
  addressByName?: boolean;
}

/**
 * Extract a first name from a display label. Returns undefined for empty labels
 * or bare emails (we don't want "Hey jon@posthog.com").
 */
export function firstNameFromLabel(
  label: string | undefined,
): string | undefined {
  if (!label) return undefined;
  const trimmed = label.trim();
  if (!trimmed || trimmed.includes("@")) return undefined;
  const first = trimmed.split(/\s+/)[0];
  return first || undefined;
}

/**
 * Build the spoken line from the agent's message body. The agent supplies only
 * the content; the app owns the task-name prefix (so the user knows which of
 * several parallel agents is talking) and, for needs-user lines, addresses the
 * user by their real name. Idempotent against an agent that already added a
 * prefix or a "Hey" greeting.
 */
export function composeUtterance({
  text,
  taskTitle,
  needsUser,
  firstName,
  addressByName,
}: ComposeInput): string {
  let body = text.trim();

  // Agent already prefixed with a task reference — return it verbatim. Checked
  // before any greeting logic so the guard stays order-independent: injecting
  // "Hey <name>," first would push the prefix past the start of the string and
  // defeat this test, producing a double prefix.
  if (TASK_PREFIX_GUARD.test(body)) return body;

  if (needsUser && addressByName && firstName) {
    // Normalize any leading greeting the agent added, then address by real name.
    body = body.replace(/^\s*hey\b[\s,]*/i, "").trimStart();
    body = `Hey ${firstName}, ${body}`;
  }

  const title = taskTitle.trim();
  if (!title) return body;
  const shortTitle =
    title.length > TASK_TITLE_MAX
      ? `${title.slice(0, TASK_TITLE_MAX)}…`
      : title;
  return `${TASK_PREFIX} '${shortTitle}' — ${body}`;
}
