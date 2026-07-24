import type { UsageOutput } from "./schemas";

export const USAGE_MONITOR_SERVICE = Symbol.for(
  "posthog.core.usageMonitorService",
);
export const USAGE_HOST = Symbol.for("posthog.core.usageHost");

export interface UsageHost {
  fetchUsage(): Promise<UsageOutput>;

  onLlmActivity(listener: () => void): void;
  offLlmActivity(listener: () => void): void;
  hasActiveSessions(): boolean;

  getThresholdsSeen(): Record<string, string>;
  setThresholdsSeen(value: Record<string, string>): void;
}

export interface UsageLogger {
  debug(message: string, ...args: unknown[]): void;
  info(message: string, ...args: unknown[]): void;
  warn(message: string, ...args: unknown[]): void;
  error(message: string, ...args: unknown[]): void;
}
