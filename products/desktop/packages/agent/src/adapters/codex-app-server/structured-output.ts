/** Parse structured output from the final message, defensively (fenced block / first object). */
export function parseStructuredOutput(
  text: string,
): Record<string, unknown> | null {
  const trimmed = text.trim();
  const candidates = [trimmed];
  const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fenced) candidates.push(fenced[1].trim());

  for (const candidate of candidates) {
    const parsed = parseJsonObject(candidate);
    if (parsed) return parsed;
  }

  // Fall back to the first balanced {...} in the prose. Balance-aware rather
  // than a greedy regex, so trailing prose containing braces cannot extend the
  // match past the object's real closing brace.
  let searchFrom = 0;
  for (let guard = 0; guard < 100; guard++) {
    const start = trimmed.indexOf("{", searchFrom);
    if (start === -1) return null;
    const end = findBalancedObjectEnd(trimmed, start);
    if (end === -1) return null;
    const parsed = parseJsonObject(trimmed.slice(start, end + 1));
    if (parsed) return parsed;
    searchFrom = start + 1;
  }
  return null;
}

function parseJsonObject(candidate: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(candidate);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
  } catch {
    // Not valid JSON; the caller tries the next candidate.
  }
  return null;
}

/** Index of the `}` closing the object opened at `start`, or -1 (string-aware). */
function findBalancedObjectEnd(text: string, start: number): number {
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let i = start; i < text.length; i++) {
    const ch = text[i];
    if (inString) {
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') inString = true;
    else if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) return i;
    }
  }
  return -1;
}
