/**
 * Replaces every `Authorization` header value with a placeholder.
 *
 * MCP server configs carry the acting user's OAuth token, an installation
 * proxy token, or the local relay secret in an `Authorization` header. Read
 * access to a run's event stream and session log is wider than control access,
 * so a reader who cannot steer the run must not get these credentials.
 *
 * Both header shapes that cross the ACP wire are covered: the `{ name, value }`
 * pairs of an MCP server config, and a plain header map keyed by header name.
 */
export function redactAuthorizationHeaders(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(redactAuthorizationHeaders);
  }
  if (value === null || typeof value !== "object" || value instanceof Date) {
    return value;
  }

  const record = value as Record<string, unknown>;
  if (isAuthorizationName(record.name) && "value" in record) {
    return { ...record, value: REDACTED };
  }

  return Object.fromEntries(
    Object.entries(record).map(([key, nestedValue]) => [
      key,
      isAuthorizationName(key) && typeof nestedValue === "string"
        ? REDACTED
        : redactAuthorizationHeaders(nestedValue),
    ]),
  );
}

const REDACTED = "[REDACTED]";

function isAuthorizationName(value: unknown): boolean {
  return typeof value === "string" && value.toLowerCase() === "authorization";
}
