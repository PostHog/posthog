/**
 * Best-effort parser for incomplete JSON streamed via Anthropic's
 * `input_json_delta` events. Used to surface tool inputs while they are still
 * being generated so the UI can show the args during execution instead of
 * waiting for the finalized assistant message.
 *
 * Strategy: walk the input tracking open `{`/`[` and quote/escape state, then
 * try a few completions in order of likelihood (close any open string, drop
 * trailing commas/colons or partial keys, then close any open brackets).
 * Returns `null` when no completion parses — callers should silently skip
 * that delta and wait for more input.
 */
export function tryParsePartialJson(s: string): unknown {
  const trimmed = s.trim();
  if (!trimmed) return null;

  // Fast path: complete JSON.
  try {
    return JSON.parse(trimmed);
  } catch {}

  const closers: string[] = [];
  let inString = false;
  let escaped = false;

  for (let i = 0; i < trimmed.length; i++) {
    const ch = trimmed[i];
    if (inString) {
      if (escaped) {
        escaped = false;
      } else if (ch === "\\") {
        escaped = true;
      } else if (ch === '"') {
        inString = false;
      }
      continue;
    }
    if (ch === '"') inString = true;
    else if (ch === "{") closers.push("}");
    else if (ch === "[") closers.push("]");
    else if (ch === "}" || ch === "]") closers.pop();
  }

  const closeBrackets = (str: string): string => {
    let out = str;
    for (let i = closers.length - 1; i >= 0; i--) out += closers[i];
    return out;
  };

  const candidates: string[] = [];

  // 1. Close any open string + brackets.
  const closedString = inString ? `${trimmed}"` : trimmed;
  candidates.push(closeBrackets(closedString));

  // 2. Drop trailing partial token (comma, colon, or `"key":`/`"key"`)
  //    and close brackets.
  let stripped = closedString.replace(/[,:]\s*$/, "");
  stripped = stripped.replace(/,?\s*"[^"]*"\s*:?\s*$/, "");
  candidates.push(closeBrackets(stripped));

  for (const candidate of candidates) {
    try {
      return JSON.parse(candidate);
    } catch {}
  }
  return null;
}
