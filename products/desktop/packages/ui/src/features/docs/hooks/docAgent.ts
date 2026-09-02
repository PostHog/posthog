/**
 * What a doc's agent runs on, with nothing to choose.
 *
 * A question about a page is not about a repository, so the run takes none, and
 * the harness and the model are fixed: an answer has to arrive while the person
 * is still looking at the page.
 *
 * The run is a cloud run, and the page can watch it: a local run keeps its
 * session in the window that started it and writes no thread, so a page could
 * only point at the task. A cloud run streams into the dock beside the page, its
 * structured result is what turns a request into a data point, and the warm pool
 * keeps one sandbox waiting for it.
 */
export const DOC_AGENT_WORKSPACE_MODE = "cloud";
export const DOC_AGENT_RUNTIME = "acp";
export const DOC_AGENT_MODEL = "gpt-5.6-luna";
/** Luna is a codex model, so the claude adapter refuses it at startup. */
export const DOC_AGENT_ADAPTER = "codex";
export const DOC_AGENT_REASONING_EFFORT = "high";
/**
 * Safe tools run without a prompt, the way Quick Ask runs them.
 *
 * A page has no surface for a permission dialog, and the person already said
 * what they want by asking for it. Anything outside the safe set still asks, in
 * the thread the margin symbol opens.
 */
export const DOC_AGENT_EXECUTION_MODE = "auto";
/** A doc run clones nothing, so it warms and activates on no branch. */
export const DOC_AGENT_BRANCH = null;

const MAX_TITLE_LENGTH = 90;

export function docTaskTitle(text: string, fallback: string): string {
  const trimmed = text.trim().replace(/\s+/g, " ");
  if (!trimmed) return fallback;
  if (trimmed.length <= MAX_TITLE_LENGTH) return trimmed;
  return `${trimmed.slice(0, MAX_TITLE_LENGTH - 1).trimEnd()}…`;
}
