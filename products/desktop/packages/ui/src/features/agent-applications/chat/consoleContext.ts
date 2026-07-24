/**
 * The agent builder's "what am I looking at" envelope. Mirrors the console: the
 * current page context is prepended to the *first* user message of a session,
 * delimited so the agent can resolve deictic references ("this agent", "this
 * session") without asking — and so the client can strip it before display.
 */

const OPEN = "[console-context]";
const CLOSE = "[/console-context]";

/** Wrap a context object in the delimited envelope (prepended to msg one). */
export function buildConsoleContextEnvelope(context: unknown): string {
  return `${OPEN}\n${JSON.stringify(context)}\n${CLOSE}`;
}

/**
 * Strip a leading console-context block (and the blank line after it) so the
 * envelope never shows in the rendered transcript. No-op when absent.
 */
export function stripConsoleContext(text: string): string {
  const start = text.indexOf(OPEN);
  if (start === -1) return text;
  const end = text.indexOf(CLOSE, start);
  if (end === -1) return text;
  const before = text.slice(0, start);
  // Only strip a *leading* envelope (allow leading whitespace before it).
  if (before.trim() !== "") return text;
  return text.slice(end + CLOSE.length).replace(/^\s*\n/, "");
}
