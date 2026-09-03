import {
  type HostLogger,
  type ScopedLogger,
  logger as uiLogger,
} from "@posthog/ui/shell/logger";
import log from "electron-log/renderer";

log.transports.console.level = "debug";

// electron-log's renderer export is a Proxy that answers any unknown property
// with a log function, `then` included. Inversify treats a thenable constant
// as an async service and throws on `get`, the shell logger swallows that, and
// every ui/core log line dies before it reaches the main process. Bind a plain
// object instead.
export const hostLog: HostLogger = {
  scope: (name: string): ScopedLogger => log.scope(name),
  info: (...args: unknown[]) => log.info(...args),
  warn: (...args: unknown[]) => log.warn(...args),
  error: (...args: unknown[]) => log.error(...args),
  debug: (...args: unknown[]) => log.debug(...args),
};

export const logger = uiLogger;
