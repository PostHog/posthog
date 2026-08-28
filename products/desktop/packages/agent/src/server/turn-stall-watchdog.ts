import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export const DEFAULT_TURN_STALL_SOFT_TIMEOUT_MS = 10 * 60 * 1000;
export const DEFAULT_TURN_STALL_HARD_TIMEOUT_MS = 45 * 60 * 1000;
export const DEFAULT_TURN_STALL_CHECK_INTERVAL_MS = 30 * 1000;
export const DEFAULT_TURN_STALL_PROBE_TIMEOUT_MS = 15 * 1000;

export type TurnStallReason = "sandbox_unresponsive" | "turn_silent";

export const TURN_STALL_CANCEL_GRACE_MS = 60_000;
export const TURN_STALL_DRAIN_POLL_MS = 500;
export const TURN_STALL_MESSAGES: Record<TurnStallReason, string> = {
  sandbox_unresponsive:
    "The sandbox stopped responding while the agent was working. Resume the task to continue.",
  turn_silent:
    "The agent produced no output for a long time and the turn was stopped. Resume the task to continue.",
};

export function readTurnStallTimeoutsFromEnv(): {
  softTimeoutMs: number;
  hardTimeoutMs: number;
} {
  return {
    softTimeoutMs: readTurnStallTimeoutMs(
      process.env.POSTHOG_TURN_STALL_SOFT_TIMEOUT_MS,
      DEFAULT_TURN_STALL_SOFT_TIMEOUT_MS,
    ),
    hardTimeoutMs: readTurnStallTimeoutMs(
      process.env.POSTHOG_TURN_STALL_HARD_TIMEOUT_MS,
      DEFAULT_TURN_STALL_HARD_TIMEOUT_MS,
    ),
  };
}

export interface TurnStallWatchdogLogger {
  debug(message: string, data?: unknown): void;
  warn(message: string, data?: unknown): void;
}

export interface TurnStallWatchdogOptions {
  softTimeoutMs?: number;
  hardTimeoutMs?: number;
  checkIntervalMs?: number;
  probe: () => Promise<boolean>;
  isWaitingOnUser?: () => boolean;
  onStall: (reason: TurnStallReason, silentMs: number) => void | Promise<void>;
  now?: () => number;
  logger?: TurnStallWatchdogLogger;
}

export class TurnStallWatchdog {
  private readonly softTimeoutMs: number;
  private readonly hardTimeoutMs: number;
  private readonly checkIntervalMs: number;
  private readonly probe: () => Promise<boolean>;
  private readonly isWaitingOnUser: () => boolean;
  private readonly onStall: TurnStallWatchdogOptions["onStall"];
  private readonly now: () => number;
  private readonly logger?: TurnStallWatchdogLogger;

  private timer: ReturnType<typeof setInterval> | null = null;
  private lastActivityAt = 0;
  private checking = false;
  private generation = 0;

  constructor(options: TurnStallWatchdogOptions) {
    this.softTimeoutMs =
      options.softTimeoutMs ?? DEFAULT_TURN_STALL_SOFT_TIMEOUT_MS;
    this.hardTimeoutMs =
      options.hardTimeoutMs ?? DEFAULT_TURN_STALL_HARD_TIMEOUT_MS;
    this.checkIntervalMs =
      options.checkIntervalMs ?? DEFAULT_TURN_STALL_CHECK_INTERVAL_MS;
    this.probe = options.probe;
    this.isWaitingOnUser = options.isWaitingOnUser ?? (() => false);
    this.onStall = options.onStall;
    this.now = options.now ?? Date.now;
    this.logger = options.logger;
  }

  get enabled(): boolean {
    return this.softTimeoutMs > 0 || this.hardTimeoutMs > 0;
  }

  get running(): boolean {
    return this.timer !== null;
  }

  start(): void {
    if (!this.enabled || this.timer) return;
    this.lastActivityAt = this.now();
    this.generation += 1;
    this.timer = setInterval(() => {
      void this.tick();
    }, this.checkIntervalMs);
    this.timer.unref?.();
  }

  stop(): void {
    if (!this.timer) return;
    clearInterval(this.timer);
    this.timer = null;
    this.generation += 1;
  }

  recordActivity(): void {
    this.lastActivityAt = this.now();
    this.generation += 1;
  }

  async tick(): Promise<void> {
    if (!this.timer || this.checking) return;
    if (this.isWaitingOnUser()) {
      this.recordActivity();
      return;
    }
    const silentMs = this.now() - this.lastActivityAt;
    if (this.hardTimeoutMs > 0 && silentMs >= this.hardTimeoutMs) {
      await this.fire("turn_silent", silentMs);
      return;
    }
    if (this.softTimeoutMs <= 0 || silentMs < this.softTimeoutMs) return;

    this.checking = true;
    const generation = this.generation;
    try {
      const responsive = await this.probe();
      if (!this.timer || generation !== this.generation) return;
      if (responsive) {
        this.logger?.debug("Turn is quiet but the sandbox still responds", {
          silentMs,
        });
        return;
      }
      await this.fire("sandbox_unresponsive", silentMs);
    } finally {
      this.checking = false;
    }
  }

  private async fire(reason: TurnStallReason, silentMs: number): Promise<void> {
    this.stop();
    this.logger?.warn("Turn stalled", { reason, silentMs });
    await this.onStall(reason, silentMs);
  }
}

export function probeSandboxResponsive(
  timeoutMs: number = DEFAULT_TURN_STALL_PROBE_TIMEOUT_MS,
): Promise<boolean> {
  return execFileAsync("/bin/sh", ["-c", "true"], { timeout: timeoutMs })
    .then(() => true)
    .catch(() => false);
}

export function readTurnStallTimeoutMs(
  value: string | undefined,
  fallback: number,
): number {
  if (value === undefined || value === "") return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}
