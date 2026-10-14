import { Buffer } from "node:buffer";
import type { Logger } from "../utils/logger";

export const AGENT_CALLBACKS_HEADER = "X-PostHog-Agent-Callbacks";

const AGENT_SENDS_CALLBACKS_CLAIM = "agent_sends_callbacks";
const HEARTBEAT_THROTTLE_MS = 30_000;
const DEFAULT_RETRY_DELAY_MS = 1_000;
const STOP_REASON_END_TURN = "end_turn";
const STOP_REASON_IDLE_RESUME = "idle_resume";

export type AgentCallback =
  | { kind: "heartbeat"; agent_active: true; activity_started: boolean }
  | {
      kind: "awaiting_input";
      agent_active: false;
      turn_completed: boolean;
      turn_succeeded: boolean;
    };

interface AgentCallbackReporterConfig {
  send: (callback: AgentCallback) => Promise<void>;
  flushEvents: () => Promise<void>;
  logger: Logger;
  now?: () => number;
  retryDelayMs?: number;
}

function isRetryableFailure(error: unknown): boolean {
  const status =
    typeof error === "object" && error !== null && "status" in error
      ? error.status
      : undefined;
  return typeof status !== "number" || status >= 500;
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
  private agentActive = false;
  private lastHeartbeatAtMs: number | null = null;
  private readonly inFlight = new Set<Promise<void>>();

  constructor(private readonly config: AgentCallbackReporterConfig) {
    this.now = config.now ?? Date.now;
    this.retryDelayMs = config.retryDelayMs ?? DEFAULT_RETRY_DELAY_MS;
  }

  agentActivity(): void {
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
    this.track(
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

  turnCompleted(stopReason: string): void {
    this.agentActive = false;
    this.track(this.reportTurnCompleted(stopReason));
  }

  async settled(): Promise<void> {
    await Promise.all(this.inFlight);
  }

  private async reportTurnCompleted(stopReason: string): Promise<void> {
    await this.config.flushEvents().catch(() => undefined);
    await this.deliver(
      {
        kind: "awaiting_input",
        agent_active: false,
        turn_completed: stopReason !== STOP_REASON_IDLE_RESUME,
        turn_succeeded: stopReason === STOP_REASON_END_TURN,
      },
      2,
    );
  }

  private track(delivery: Promise<void>): void {
    const tracked = delivery.finally(() => {
      this.inFlight.delete(tracked);
    });
    this.inFlight.add(tracked);
  }

  private async deliver(
    callback: AgentCallback,
    attempts: number,
  ): Promise<void> {
    for (let attempt = 1; attempt <= attempts; attempt++) {
      try {
        await this.config.send(callback);
        return;
      } catch (error) {
        this.config.logger.warn("Agent callback failed", {
          kind: callback.kind,
          attempt,
          error: error instanceof Error ? error.message : String(error),
        });
        if (attempt === attempts || !isRetryableFailure(error)) {
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, this.retryDelayMs));
      }
    }
  }
}

export function createAgentCallbackReporter(options: {
  eventIngestToken: string;
  eventIngestBaseUrl?: string;
  send: (callback: AgentCallback) => Promise<void>;
  flushEvents: () => Promise<void>;
  logger: Logger;
}): AgentCallbackReporter | null {
  if (
    !options.eventIngestBaseUrl ||
    !agentSendsCallbacks(options.eventIngestToken)
  ) {
    return null;
  }
  return new AgentCallbackReporter({
    send: options.send,
    flushEvents: options.flushEvents,
    logger: options.logger,
  });
}
