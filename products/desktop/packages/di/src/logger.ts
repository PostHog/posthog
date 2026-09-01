export interface ScopedLogger {
  debug(...args: unknown[]): void;
  info(...args: unknown[]): void;
  warn(...args: unknown[]): void;
  error(...args: unknown[]): void;
}

export interface RootLogger extends ScopedLogger {
  scope(name: string): ScopedLogger;
}

export const ROOT_LOGGER = Symbol.for("posthog.logger");
