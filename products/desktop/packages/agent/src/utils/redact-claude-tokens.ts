export function redactClaudeTokens(value: string): string;
export function redactClaudeTokens(
  value: string | undefined,
): string | undefined;
export function redactClaudeTokens(value: unknown): unknown;
export function redactClaudeTokens(value: unknown): unknown {
  if (typeof value === "string")
    return value.replace(/sk-ant-oat01-[A-Za-z0-9_-]+/g, "[REDACTED]");
  if (Array.isArray(value)) return value.map(redactClaudeTokens);
  if (value instanceof Error)
    return {
      name: value.name,
      message: redactClaudeTokens(value.message),
      stack: redactClaudeTokens(value.stack),
    };
  if (value instanceof Date) return value;
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, nested]) => [
        key,
        redactClaudeTokens(nested),
      ]),
    );
  }
  return value;
}
