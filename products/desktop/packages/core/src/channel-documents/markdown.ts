/**
 * Pure markdown helpers for channel documents (shared todo/plan docs).
 *
 * Capture formatting turns a text selection from a chat message into an
 * appendable markdown block; checkbox toggling maps a rendered GFM task-list
 * checkbox back onto its source line so a click can flip it. Both are pure so
 * the concurrency-sensitive write path stays a tiny, testable string transform.
 */

export interface CaptureSource {
  /** Label for the provenance link, e.g. the task title. */
  label: string;
  /** Deep link back to where the text was captured, e.g. posthog-code://task/<id>. */
  url: string;
}

const TODO_ITEM_MAX_LENGTH = 200;

function collapseWhitespace(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

function sourceSuffix(source: CaptureSource | undefined): string {
  if (!source) return "";
  const label = collapseWhitespace(source.label) || "source";
  // Escape the few markdown-link-breaking characters a task title can carry.
  const safeLabel = label.replace(/([[\]()])/g, "\\$1");
  return ` (from [${safeLabel}](${source.url}))`;
}

/** One checklist item: the selection collapsed to a single line, provenance last. */
export function formatTodoCapture(
  text: string,
  source?: CaptureSource,
): string {
  let item = collapseWhitespace(text);
  if (item.length > TODO_ITEM_MAX_LENGTH) {
    item = `${item.slice(0, TODO_ITEM_MAX_LENGTH - 1).trimEnd()}…`;
  }
  return `- [ ] ${item}${sourceSuffix(source)}`;
}

/** A quoted block preserving the selection's lines, provenance on its own line. */
export function formatPlanCapture(
  text: string,
  source?: CaptureSource,
): string {
  const lines = text
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((line) => line.trimEnd());
  while (lines.length > 0 && lines[0]?.trim() === "") lines.shift();
  while (lines.length > 0 && lines[lines.length - 1]?.trim() === "")
    lines.pop();
  const quoted = lines.map((line) => (line ? `> ${line}` : ">")).join("\n");
  const suffix = sourceSuffix(source);
  return suffix ? `${quoted}\n>${suffix}` : quoted;
}

const TASK_CHECKBOX_PATTERN = /^(\s*(?:[-*+]|\d+[.)])\s+\[)([ xX])(\])/;

/**
 * Flip the `index`-th (0-based, in source order) GFM task checkbox in a
 * markdown document, skipping fenced code blocks — mirroring how rendered
 * checkboxes are counted. Returns null when there aren't that many checkboxes,
 * so a stale click after a concurrent edit becomes a no-op instead of flipping
 * the wrong line.
 */
export function toggleTaskCheckbox(
  content: string,
  index: number,
): string | null {
  if (index < 0) return null;
  const lines = content.split("\n");
  let seen = 0;
  let inFence = false;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] ?? "";
    if (/^\s*(```|~~~)/.test(line)) {
      inFence = !inFence;
      continue;
    }
    if (inFence) continue;
    const match = TASK_CHECKBOX_PATTERN.exec(line);
    if (!match) continue;
    if (seen === index) {
      const flipped = match[2] === " " ? "x" : " ";
      lines[i] = line.replace(TASK_CHECKBOX_PATTERN, `$1${flipped}$3`);
      return lines.join("\n");
    }
    seen++;
  }
  return null;
}
