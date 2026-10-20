import { Buffer } from "node:buffer";
import type { ProcessKilledParams } from "../acp-extensions";
import type { AgentErrorClassification } from "../adapters/error-classification";
import { AGENT_CALLBACK_TIMEOUT_MS } from "../posthog-api";
import type { Logger } from "../utils/logger";

export const AGENT_CALLBACKS_HEADER = "X-PostHog-Agent-Callbacks";

const AGENT_SENDS_CALLBACKS_CLAIM = "agent_sends_callbacks";
const HEARTBEAT_THROTTLE_MS = 30_000;
const DEFAULT_RETRY_DELAY_MS = 500;
const DEFAULT_ACK_TIMEOUT_MS = 30_000;
const RUN_EVENT_ATTEMPTS = 3;
const RUN_ENDED_STATUS = 409;
const STOP_REASON_END_TURN = "end_turn";
const STOP_REASON_IDLE_RESUME = "idle_resume";
const BUDGET_STEER_FIELDS = [
  "stage",
  "mode",
  "delivered",
  "spent_usd",
  "cap_usd",
  "threshold_spent_usd",
  "threshold_at",
  "delivered_at",
] as const;

export const AGENT_CALLBACK_SETTLE_BUDGET_MS =
  2 * AGENT_CALLBACK_TIMEOUT_MS + DEFAULT_RETRY_DELAY_MS;

type BootMilestone = "command_dispatched" | "agent_activity";

export type RunFailureType =
  | "agent_reported"
  | "agent_server_crash"
  | AgentErrorClassification;

export type RunEvent =
  | { type: "started"; agent_version: string; benjamin_version?: string }
  | {
      type: "failed";
      error_type: RunFailureType;
      cause: string;
      agent_version?: string;
    }
  | { type: "branch_changed"; branch: string }
  | { type: "pr_detected"; pr_url: string; branch?: string }
  | { type: "structured_output"; output: Record<string, unknown> }
  | {
      type: "usage";
      token_usage?: Record<string, unknown>;
      budget_guard?: Record<string, unknown>;
    };

export type AgentCallback =
  | { kind: "heartbeat"; agent_active: true; activity_started: boolean }
  | { kind: "agent_activity"; agent_active: true }
  | { kind: "command_dispatched"; agent_active: false }
  | {
      kind: "awaiting_input";
      agent_active: false;
      turn_completed: boolean;
      turn_succeeded: boolean;
      sequence?: number;
    }
  | { kind: "turn_failed"; agent_active: false; sequence?: number }
  | ({
      kind: "budget_steer";
      agent_active: false;
      sequence: number;
      timestamp: string;
    } & Partial<Record<(typeof BUDGET_STEER_FIELDS)[number], unknown>>)
  | {
      kind: "process_killed";
      agent_active: false;
      sequence: number;
      process_killed: {
        comm: string;
        signal: string;
        tree_rss_bytes: number;
        memory_current_bytes: number;
        memory_limit_bytes: number;
      };
    }
  | { kind: "run_event"; agent_active: false; event: RunEvent };

export type DeliveryOutcome = "dispatched" | "skipped" | "refused" | "failed";

interface AgentCallbackReporterConfig {
  sendsCallbacks: boolean;
  send: (callback: AgentCallback) => Promise<boolean>;
  awaitEventAck: () => Promise<number | null>;
  logger: Logger;
  now?: () => number;
  retryDelayMs?: number;
  ackTimeoutMs?: number;
}

function isRetryableFailure(error: unknown): boolean {
  const status = errorStatus(error);
  return status === undefined || status >= 500;
}

function errorStatus(error: unknown): number | undefined {
  return typeof error === "object" &&
    error !== null &&
    "status" in error &&
    typeof error.status === "number"
    ? error.status
    : undefined;
}

function withSequence(sequence: number | null): { sequence?: number } {
  return sequence === null ? {} : { sequence };
}

export function agentSendsCallbacks(eventIngestToken: string): boolean {
  const payload = eventIngestToken.split(".")[1];
  if (!payload) {
    return false;
  }
  try {
    const claims: unknown = JSON.parse(
      Buffer.from(payload, "base64url").toString("utf8"),
    );
    return (
      typeof claims === "object" &&
      claims !== null &&
      AGENT_SENDS_CALLBACKS_CLAIM in claims &&
      claims[AGENT_SENDS_CALLBACKS_CLAIM] === true
    );
  } catch {
    return false;
  }
}

export class AgentCallbackReporter {
  private readonly now: () => number;
  private readonly retryDelayMs: number;
  private readonly ackTimeoutMs: number;
  private readonly reportedMilestones = new Set<BootMilestone>();
  private queue: Promise<void> = Promise.resolve();
  private agentActive = false;
  private lastHeartbeatAtMs: number | null = null;
  private ackWaitsReleased = false;
  private readonly pendingAckWaits = new Set<() => void>();
  private runQueue: Promise<unknown> = Promise.resolve();
  private runEnded = false;

  get sendsCallbacks(): boolean {
    return this.config.sendsCallbacks;
  }

  constructor(private readonly config: AgentCallbackReporterConfig) {
    this.now = config.now ?? Date.now;
    this.retryDelayMs = config.retryDelayMs ?? DEFAULT_RETRY_DELAY_MS;
    this.ackTimeoutMs = config.ackTimeoutMs ?? DEFAULT_ACK_TIMEOUT_MS;
  }

  agentActivity(generating: boolean): void {
    if (!this.config.sendsCallbacks) {
      return;
    }
    if (generating) {
      this.reportMilestone({ kind: "agent_activity", agent_active: true });
    }
    const activityStarted = !this.agentActive;
    this.agentActive = true;

    const now = this.now();
    const heartbeatDue =
      this.lastHeartbeatAtMs === null ||
      now - this.lastHeartbeatAtMs >= HEARTBEAT_THROTTLE_MS;
    if (!heartbeatDue && !activityStarted) {
      return;
    }
    this.lastHeartbeatAtMs = now;
    this.enqueue(() =>
      this.deliver(
        {
          kind: "heartbeat",
          agent_active: true,
          activity_started: activityStarted,
        },
        1,
      ),
    );
  }

  commandDispatched(): void {
    this.reportMilestone({ kind: "command_dispatched", agent_active: false });
  }

  turnCompleted(stopReason: string): void {
    this.agentActive = false;
    this.reportAfterAck((sequence) => ({
      kind: "awaiting_input",
      agent_active: false,
      turn_completed: stopReason !== STOP_REASON_IDLE_RESUME,
      turn_succeeded: stopReason === STOP_REASON_END_TURN,
      ...withSequence(sequence),
    }));
  }

  turnFailed(): void {
    this.agentActive = false;
    this.reportAfterAck((sequence) => ({
      kind: "turn_failed",
      agent_active: false,
      ...withSequence(sequence),
    }));
  }

  budgetSteer(steer: Record<string, unknown>): void {
    const timestamp = new Date(this.now()).toISOString();
    this.reportAfterAck((sequence) => {
      if (sequence === null) {
        return null;
      }
      const callback: AgentCallback = {
        kind: "budget_steer",
        agent_active: false,
        sequence,
        timestamp,
      };
      for (const field of BUDGET_STEER_FIELDS) {
        callback[field] = steer[field];
      }
      return callback;
    });
  }

  processKilled(kill: ProcessKilledParams): void {
    this.reportAfterAck((sequence) =>
      sequence === null
        ? null
        : {
            kind: "process_killed",
            agent_active: false,
            sequence,
            process_killed: {
              comm: kill.comm,
              signal: kill.signal,
              tree_rss_bytes: Math.trunc(kill.treeRssBytes),
              memory_current_bytes: Math.trunc(kill.memoryCurrentBytes),
              memory_limit_bytes: Math.trunc(kill.memoryLimitBytes),
            },
          },
    );
  }

  reportRun(event: RunEvent): Promise<DeliveryOutcome> {
    if (this.runEnded) {
      this.config.logger.warn("Dropped run event after the run ended", {
        type: event.type,
      });
      return Promise.resolve("skipped");
    }
    const callback: AgentCallback = {
      kind: "run_event",
      agent_active: false,
      event,
    };
    if (event.type === "failed") {
      this.runEnded = true;
      const delivered = this.deliver(callback, RUN_EVENT_ATTEMPTS);
      this.runQueue = Promise.all([this.runQueue, delivered]);
      return delivered;
    }
    const delivered = this.runQueue.then(() =>
      this.deliver(callback, RUN_EVENT_ATTEMPTS),
    );
    this.runQueue = delivered;
    return delivered;
  }

  async settled(): Promise<void> {
    await Promise.all([this.queue, this.runQueue]);
  }

  stopWaitingForAcks(): void {
    this.ackWaitsReleased = true;
    for (const release of this.pendingAckWaits) {
      release();
    }
    this.pendingAckWaits.clear();
  }

  private reportMilestone(
    callback: Extract<AgentCallback, { kind: BootMilestone }>,
  ): void {
    if (!this.config.sendsCallbacks) {
      return;
    }
    if (this.reportedMilestones.has(callback.kind)) {
      return;
    }
    this.reportedMilestones.add(callback.kind);
    this.enqueue(async () => {
      const outcome = await this.deliver(callback, 1);
      if (outcome === "skipped" || outcome === "failed") {
        this.reportedMilestones.delete(callback.kind);
      }
    });
  }

  private reportAfterAck(
    build: (sequence: number | null) => AgentCallback | null,
  ): void {
    if (!this.config.sendsCallbacks) {
      return;
    }
    const acked = this.waitForAck();
    this.enqueue(async () => {
      const callback = build(await acked);
      if (callback === null) {
        this.config.logger.warn(
          "Dropped agent callback because its event was never acknowledged",
        );
        return;
      }
      await this.deliver(callback, 2);
    });
  }

  private waitForAck(): Promise<number | null> {
    if (this.ackWaitsReleased) {
      return Promise.resolve(null);
    }
    return new Promise((resolve) => {
      const finish = (sequence: number | null) => {
        clearTimeout(timer);
        this.pendingAckWaits.delete(release);
        resolve(sequence);
      };
      const release = () => finish(null);
      const timer = setTimeout(release, this.ackTimeoutMs);
      timer.unref?.();
      this.pendingAckWaits.add(release);
      this.config.awaitEventAck().then(finish, release);
    });
  }

  private enqueue(task: () => Promise<unknown>): void {
    this.queue = this.queue.then(async () => {
      await task();
    });
  }

  private async deliver(
    callback: AgentCallback,
    attempts: number,
  ): Promise<DeliveryOutcome> {
    for (let attempt = 1; attempt <= attempts; attempt++) {
      try {
        return (await this.config.send(callback)) ? "dispatched" : "skipped";
      } catch (error) {
        this.config.logger.warn("Agent callback failed", {
          kind: callback.kind,
          attempt,
          error: error instanceof Error ? error.message : String(error),
        });
        if (errorStatus(error) === RUN_ENDED_STATUS) {
          this.runEnded = true;
        }
        if (!isRetryableFailure(error)) {
          return "refused";
        }
        if (attempt < attempts) {
          await new Promise((resolve) =>
            setTimeout(resolve, this.retryDelayMs),
          );
        }
      }
    }
    return "failed";
  }
}

export function createAgentCallbackReporter(options: {
  eventIngestToken: string | undefined;
  send: (callback: AgentCallback) => Promise<boolean>;
  awaitEventAck: () => Promise<number | null>;
  logger: Logger;
}): AgentCallbackReporter {
  return new AgentCallbackReporter({
    sendsCallbacks:
      options.eventIngestToken !== undefined &&
      agentSendsCallbacks(options.eventIngestToken),
    send: options.send,
    awaitEventAck: options.awaitEventAck,
    logger: options.logger,
  });
}
