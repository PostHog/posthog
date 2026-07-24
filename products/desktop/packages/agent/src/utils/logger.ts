import type { LogLevel as LogLevelType, OnLogCallback } from "../types";

export interface LoggerConfig {
  debug?: boolean;
  prefix?: string;
  scope?: string;
  onLog?: OnLogCallback;
}

export class Logger {
  private debugEnabled: boolean;
  private prefix: string;
  private scope: string;
  private onLog?: OnLogCallback;

  constructor(config: LoggerConfig = {}) {
    this.debugEnabled = config.debug ?? false;
    this.prefix = config.prefix ?? "[PostHog Agent]";
    this.scope = config.scope ?? "agent";
    this.onLog = config.onLog;
  }

  private formatMessage(
    level: string,
    message: string,
    data?: unknown,
  ): string {
    const timestamp = new Date().toISOString();
    const base = `${timestamp} ${this.prefix} [${level}] ${message}`;

    if (data !== undefined) {
      return `${base} ${JSON.stringify(data, null, 2)}`;
    }

    return base;
  }

  private emitLog(level: LogLevelType, message: string, data?: unknown) {
    if (this.onLog) {
      this.onLog(level, this.scope, message, data);
      return;
    }

    const shouldLog = this.debugEnabled || level === "error";

    if (shouldLog) {
      console[level](this.formatMessage(level.toLowerCase(), message, data));
    }
  }

  error(message: string, error?: Error | unknown) {
    const data =
      error instanceof Error
        ? { message: error.message, stack: error.stack }
        : error;

    this.emitLog("error", message, data);
  }

  warn(message: string, data?: unknown) {
    this.emitLog("warn", message, data);
  }

  info(message: string, data?: unknown) {
    this.emitLog("info", message, data);
  }

  debug(message: string, data?: unknown) {
    this.emitLog("debug", message, data);
  }

  child(childPrefix: string): Logger {
    return new Logger({
      debug: this.debugEnabled,
      prefix: `${this.prefix} [${childPrefix}]`,
      scope: `${this.scope}:${childPrefix}`,
      onLog: this.onLog,
    });
  }
}
