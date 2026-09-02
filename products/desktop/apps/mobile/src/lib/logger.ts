// TODO: Set up proper production logging
// Currently, all logs are disabled in production builds.

type LogFn = (message: string, ...args: unknown[]) => void;

interface Logger {
  debug: LogFn;
  info: LogFn;
  warn: LogFn;
  error: LogFn;
  scope: (name: string) => Logger;
}

function createLogger(scope?: string): Logger {
  const prefix = scope ? `[${scope}]` : "";

  if (!__DEV__) {
    // Production: no-op for all log methods
    const noop: LogFn = () => {};
    return {
      debug: noop,
      info: noop,
      warn: noop,
      error: noop,
      scope: () => createLogger(scope),
    };
  }

  // Development: log everything
  return {
    debug: (message, ...args) => console.debug(prefix, message, ...args),
    info: (message, ...args) => console.info(prefix, message, ...args),
    warn: (message, ...args) => console.warn(prefix, message, ...args),
    error: (message, ...args) => console.error(prefix, message, ...args),
    scope: (name) => createLogger(scope ? `${scope}:${name}` : name),
  };
}

export const logger = createLogger();
export type { Logger };
