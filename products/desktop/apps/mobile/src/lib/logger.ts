import { appendLogEntry, type LogLevel } from "@/lib/logBuffer";

type LogFn = (message: string, ...args: unknown[]) => void;

interface Logger {
  debug: LogFn;
  info: LogFn;
  warn: LogFn;
  error: LogFn;
  scope: (name: string) => Logger;
}

// Console output is dev-only; the ring buffer always captures so the staff
// debug-log screen (Settings → Debug logs) works in production builds too.
function createLogger(scope?: string): Logger {
  const prefix = scope ? `[${scope}]` : "";
  const scopeName = scope ?? "app";

  const emit =
    (level: LogLevel): LogFn =>
    (message, ...args) => {
      appendLogEntry(level, scopeName, message, args);
      if (__DEV__) {
        console[level](prefix, message, ...args);
      }
    };

  return {
    debug: emit("debug"),
    info: emit("info"),
    warn: emit("warn"),
    error: emit("error"),
    scope: (name) => createLogger(scope ? `${scope}:${name}` : name),
  };
}

export const logger = createLogger();
export type { Logger };
