import type { LogLevel as LogLevelType, OnLogCallback } from "../types";
import { redactSecrets } from "./redact-secrets";

function toJsonValue(value: unknown): unknown {
  try {
    return JSON.parse(JSON.stringify(value));
  } catch {
    return String(value);
  }
}

const LEVEL_RANK: Record<LogLevelType, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
};

export type LogFormat = "text" | "json";

export interface LoggerConfig {
  debug?: boolean;
  level?: LogLevelType;
  format?: LogFormat;
  prefix?: string;
  scope?: string;
  onLog?: OnLogCallback;
}

export class Logger {
  private debugEnabled: boolean;
  private minLevel?: LogLevelType;
  private format: LogFormat;
  private prefix: string;
  private scope: string;
  private onLog?: OnLogCallback;

  constructor(config: LoggerConfig = {}) {
    this.debugEnabled = config.debug ?? false;
    this.minLevel = config.level;
    this.format = config.format ?? "text";
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

    if (this.format === "json") {
      return JSON.stringify({
        timestamp,
        level,
        prefix: this.prefix,
        message,
        ...(data !== undefined && { data }),
      });
    }

    const base = `${timestamp} ${this.prefix} [${level}] ${message}`;

    if (data !== undefined) {
      return `${base} ${JSON.stringify(data, null, 2)}`;
    }

    return base;
  }

  private emitLog(level: LogLevelType, message: string, data?: unknown) {
    message = redactSecrets(message) as string;
    data = redactSecrets(data);
    if (this.onLog) {
      this.onLog(level, this.scope, message, data);
      return;
    }

    const shouldLog = this.minLevel
      ? LEVEL_RANK[level] >= LEVEL_RANK[this.minLevel]
      : this.debugEnabled || level === "error";

    if (shouldLog) {
      console[level](this.formatMessage(level.toLowerCase(), message, data));
    }
  }

  error(message: string, error?: Error | unknown) {
    const data =
      error instanceof Error
        ? {
            message: error.message,
            stack: error.stack,
            ...("code" in error &&
              error.code !== undefined && { code: error.code }),
            ...("data" in error &&
              error.data !== undefined && { data: toJsonValue(error.data) }),
          }
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
      level: this.minLevel,
      format: this.format,
      prefix: `${this.prefix} [${childPrefix}]`,
      scope: `${this.scope}:${childPrefix}`,
      onLog: this.onLog,
    });
  }
}
