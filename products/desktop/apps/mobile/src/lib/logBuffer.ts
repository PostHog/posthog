export type LogLevel = "debug" | "info" | "warn" | "error";

export interface LogEntry {
  ts: number;
  level: LogLevel;
  scope: string;
  message: string;
  /** Stringified extra args, truncated — best-effort, never throws. */
  details?: string;
}

const MAX_ENTRIES = 500;
const MAX_DETAIL_CHARS = 600;

const entries: LogEntry[] = [];
const listeners = new Set<() => void>();

function serializeArg(arg: unknown): string {
  if (arg instanceof Error) return `${arg.name}: ${arg.message}`;
  if (typeof arg === "string") return arg;
  try {
    return JSON.stringify(arg) ?? String(arg);
  } catch {
    return String(arg);
  }
}

/**
 * In-memory ring buffer behind the app logger. Always on (cheap, capped) so
 * the staff debug-log screen has something to show even in production
 * builds, where console output is disabled.
 */
export function appendLogEntry(
  level: LogLevel,
  scope: string,
  message: string,
  args: unknown[],
): void {
  const details =
    args.length > 0
      ? args.map(serializeArg).join(" ").slice(0, MAX_DETAIL_CHARS)
      : undefined;
  entries.push({ ts: Date.now(), level, scope, message, details });
  if (entries.length > MAX_ENTRIES) {
    entries.splice(0, entries.length - MAX_ENTRIES);
  }
  for (const listener of listeners) listener();
}

/** Newest last. The returned array is a snapshot copy. */
export function getLogEntries(): LogEntry[] {
  return entries.slice();
}

export function clearLogEntries(): void {
  entries.length = 0;
  for (const listener of listeners) listener();
}

export function subscribeToLogEntries(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function formatLogEntries(logEntries: readonly LogEntry[]): string {
  return logEntries
    .map(
      (e) =>
        `${new Date(e.ts).toISOString()} ${e.level.toUpperCase().padEnd(5)} [${e.scope}] ${e.message}${e.details ? ` ${e.details}` : ""}`,
    )
    .join("\n");
}
