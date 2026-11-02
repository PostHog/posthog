const MAX_TOOL_NAME_LENGTH = 64;

/**
 * Build a pi-compatible tool name: `<prefix>_<server>_<tool>`.
 * Sanitized to [a-zA-Z0-9_]. Names longer than 64 chars are truncated with a
 * short hash suffix so distinct long names cannot collide after truncation.
 */
export function buildToolName(
  prefix: string,
  serverName: string,
  toolName: string,
): string {
  const raw = `${prefix}_${serverName}_${toolName}`;
  const safe = raw.replace(/[^a-zA-Z0-9_]/g, "_");
  if (safe.length <= MAX_TOOL_NAME_LENGTH) return safe;
  const hash = Math.abs(
    [...safe].reduce((acc, c) => ((acc << 5) - acc + c.charCodeAt(0)) | 0, 0),
  )
    .toString(36)
    .slice(0, 8);
  return `${safe.slice(0, MAX_TOOL_NAME_LENGTH - hash.length - 1)}_${hash}`;
}
