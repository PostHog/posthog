import { Buffer } from "node:buffer";
import { POSTHOG_NOTIFICATIONS } from "../acp-extensions";
import type { Logger } from "../utils/logger";

export const AGENT_CALLBACKS_HEADER = "X-PostHog-Agent-Callbacks";

const AGENT_SENDS_CALLBACKS_CLAIM = "agent_sends_callbacks";
const HEARTBEAT_THROTTLE_MS = 30_000;
const DEFAULT_RETRY_DELAY_MS = 1_000;
const STOP_REASON_END_TURN = "end_turn";
const STOP_REASON_IDLE_RESUME = "idle_resume";
const STOP_REASON_ERROR = "error";
const PI_TURN_COMPLETED = "turn_completed";
const SESSION_UPDATE_METHOD = "session/update";
const ACP_GENERATION_UPDATES = new Set([
  "agent_message",
  "agent_message_chunk",
  "agent_thought_chunk",
  "tool_call",
  "tool_call_update",
]);
const PI_GENERATION_EVENTS = new Set([
  "assistant_message_chunk",
  "assistant_thought_chunk",
  "tool_call_started",
  "tool_call_updated",
]);

export type AgentCallbackKind =
  | "heartbeat"
  | "awaiting_input"
  | "turn_failed"
  | "command_dispatched"
  | "agent_activity"
  | "budget_steer"
  | "process_killed";

export interface AgentCallback {
  kind: AgentCallbackKind;
  agent_active: boolean;
  [field: string]: unknown;
}

const RETRYABLE_KINDS: ReadonlySet<AgentCallbackKind> = new Set([
  "awaiting_input",
  "turn_failed",
  "budget_steer",
  "process_killed",
]);

type JsonObject = Record<string, unknown>;

type DeliveryOutcome = "dispatched" | "skipped" | "refused" | "failed";

interface AgentCallbackReporterConfig {
  send: (callback: AgentCallback) => Promise<boolean>;
  logger: Logger;
  now?: () => number;
  retryDelayMs?: number;
}

function asObject(value: unknown): JsonObject | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonObject)
    : null;
}

function notificationOf(event: JsonObject): JsonObject | null {
  return event.type === "notification" ? asObject(event.notification) : null;
}

function piEventOf(event: JsonObject): JsonObject | null {
  return event.type === "pi_event" ? asObject(event.event) : null;
}

function piTurnCompletedOf(event: JsonObject): JsonObject | null {
  const piEvent = piEventOf(event);
  return piEvent?.type === PI_TURN_COMPLETED ? piEvent : null;
}

function isTurnComplete(event: JsonObject): boolean {
  if (event.type === "pi_event") {
    return piTurnCompletedOf(event) !== null;
  }
  const notification = notificationOf(event);
  if (!notification) {
    return false;
  }
  return (
    notification.method === POSTHOG_NOTIFICATIONS.TURN_COMPLETE ||
    asObject(notification.result)?.stopReason === STOP_REASON_END_TURN
  );
}

function isPiTurnError(event: JsonObject): boolean {
  return piTurnCompletedOf(event)?.stopReason === STOP_REASON_ERROR;
}

function turnSucceeded(event: JsonObject): boolean {
  if (event.type === "pi_event") {
    return piTurnCompletedOf(event)?.stopReason === STOP_REASON_END_TURN;
  }
  const notification = notificationOf(event);
  if (!notification) {
    return false;
  }
  const payload =
    notification.method === POSTHOG_NOTIFICATIONS.TURN_COMPLETE
      ? notification.params
      : notification.result;
  return asObject(payload)?.stopReason === STOP_REASON_END_TURN;
}

function isIdleResumeTurnComplete(event: JsonObject): boolean {
  const notification = notificationOf(event);
  return (
    notification?.method === POSTHOG_NOTIFICATIONS.TURN_COMPLETE &&
    asObject(notification.params)?.stopReason === STOP_REASON_IDLE_RESUME
  );
}

function isSessionUpdate(event: JsonObject): boolean {
  return notificationOf(event)?.method === SESSION_UPDATE_METHOD;
}

function isCommandDispatched(event: JsonObject): boolean {
  return (
    notificationOf(event)?.method === POSTHOG_NOTIFICATIONS.COMMAND_DISPATCHED
  );
}

function isGenerationEvent(event: JsonObject): boolean {
  if (event.type === "pi_event") {
    return PI_GENERATION_EVENTS.has(String(piEventOf(event)?.type));
  }
  if (!isSessionUpdate(event)) {
    return false;
  }
  const update = asObject(asObject(notificationOf(event)?.params)?.update);
  return (
    update !== null && ACP_GENERATION_UPDATES.has(String(update.sessionUpdate))
  );
}

function byteCount(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? Math.trunc(value)
    : null;
}

function budgetSteerCallback(
  sequence: number,
  event: JsonObject,
): AgentCallback | null {
  const notification = notificationOf(event);
  const params = asObject(notification?.params);
  if (
    notification?.method !== POSTHOG_NOTIFICATIONS.BUDGET_STEER ||
    params === null
  ) {
    return null;
  }
  return {
    kind: "budget_steer",
    agent_active: false,
    sequence,
    timestamp:
      typeof event.timestamp === "string" ? event.timestamp : undefined,
    stage: params.stage,
    mode: params.mode,
    delivered: params.delivered,
    spent_usd: params.spent_usd,
    cap_usd: params.cap_usd,
    threshold_spent_usd: params.threshold_spent_usd,
    threshold_at: params.threshold_at,
    delivered_at: params.delivered_at,
  };
}

function processKilledCallback(
  sequence: number,
  event: JsonObject,
): AgentCallback | null {
  const notification = notificationOf(event);
  const params = asObject(notification?.params);
  if (
    notification?.method !== POSTHOG_NOTIFICATIONS.PROCESS_KILLED ||
    params === null
  ) {
    return null;
  }
  const treeRssBytes = byteCount(params.treeRssBytes);
  const memoryCurrentBytes = byteCount(params.memoryCurrentBytes);
  const memoryLimitBytes = byteCount(params.memoryLimitBytes);
  if (
    typeof params.comm !== "string" ||
    typeof params.signal !== "string" ||
    treeRssBytes === null ||
    memoryCurrentBytes === null ||
    memoryLimitBytes === null
  ) {
    return null;
  }
  return {
    kind: "process_killed",
    agent_active: false,
    sequence,
    process_killed: {
      comm: params.comm,
      signal: params.signal,
      tree_rss_bytes: treeRssBytes,
      memory_current_bytes: memoryCurrentBytes,
      memory_limit_bytes: memoryLimitBytes,
    },
  };
}

function acceptedEventCallback(
  sequence: number,
  event: JsonObject,
): AgentCallback | null {
  return (
    budgetSteerCallback(sequence, event) ??
    processKilledCallback(sequence, event)
  );
}

function isRetryableFailure(error: unknown): boolean {
  const status = asObject(error)?.status;
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
    return asObject(claims)?.[AGENT_SENDS_CALLBACKS_CLAIM] === true;
  } catch {
    return false;
  }
}

export class AgentCallbackReporter {
  private readonly now: () => number;
  private readonly retryDelayMs: number;
  private agentActive = false;
  private commandDispatchedSent = false;
  private agentActivitySent = false;
  private lastHeartbeatAtMs: number | null = null;
  private readonly inFlight = new Set<Promise<void>>();

  constructor(private readonly config: AgentCallbackReporterConfig) {
    this.now = config.now ?? Date.now;
    this.retryDelayMs = config.retryDelayMs ?? DEFAULT_RETRY_DELAY_MS;
  }

  observe(event: JsonObject): void {
    this.reportBootMilestone(event);
    this.reportTurnState(event);
  }

  awaitsAcceptance(event: JsonObject): boolean {
    return acceptedEventCallback(0, event) !== null;
  }

  observeAccepted(sequence: number, event: JsonObject): void {
    const callback = acceptedEventCallback(sequence, event);
    if (callback) {
      this.dispatch(callback);
    }
  }

  private reportBootMilestone(event: JsonObject): void {
    if (isCommandDispatched(event) && !this.commandDispatchedSent) {
      this.commandDispatchedSent = true;
      this.dispatch({ kind: "command_dispatched", agent_active: false }, () => {
        this.commandDispatchedSent = false;
      });
    } else if (isGenerationEvent(event) && !this.agentActivitySent) {
      this.agentActivitySent = true;
      this.dispatch({ kind: "agent_activity", agent_active: true }, () => {
        this.agentActivitySent = false;
      });
    }
  }

  private reportTurnState(event: JsonObject): void {
    if (isTurnComplete(event)) {
      this.agentActive = false;
      if (isPiTurnError(event)) {
        this.dispatch({ kind: "turn_failed", agent_active: false });
      } else {
        this.dispatch({
          kind: "awaiting_input",
          agent_active: false,
          turn_completed: !isIdleResumeTurnComplete(event),
          turn_succeeded: turnSucceeded(event),
        });
      }
      return;
    }

    let activityStarted = false;
    if (isSessionUpdate(event) || isGenerationEvent(event)) {
      activityStarted = !this.agentActive;
      this.agentActive = true;
    }
    if (!this.agentActive) {
      return;
    }

    const now = this.now();
    const heartbeatDue =
      this.lastHeartbeatAtMs === null ||
      now - this.lastHeartbeatAtMs >= HEARTBEAT_THROTTLE_MS;
    if (heartbeatDue) {
      this.lastHeartbeatAtMs = now;
    }
    if (!heartbeatDue && !activityStarted) {
      return;
    }
    this.dispatch({
      kind: "heartbeat",
      agent_active: true,
      activity_started: activityStarted,
    });
  }

  async settled(): Promise<void> {
    await Promise.all(this.inFlight);
  }

  private dispatch(callback: AgentCallback, releaseClaim?: () => void): void {
    const delivery = this.deliver(callback)
      .then((outcome) => {
        if (outcome === "skipped" || outcome === "failed") {
          releaseClaim?.();
        }
      })
      .finally(() => {
        this.inFlight.delete(delivery);
      });
    this.inFlight.add(delivery);
  }

  private async deliver(callback: AgentCallback): Promise<DeliveryOutcome> {
    const attempts = RETRYABLE_KINDS.has(callback.kind) ? 2 : 1;
    for (let attempt = 1; attempt <= attempts; attempt++) {
      try {
        if (await this.config.send(callback)) {
          return "dispatched";
        }
        this.config.logger.warn("Agent callback was not dispatched", {
          kind: callback.kind,
        });
        return "skipped";
      } catch (error) {
        this.config.logger.warn("Agent callback failed", {
          kind: callback.kind,
          attempt,
          error: error instanceof Error ? error.message : String(error),
        });
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
  eventIngestToken: string;
  eventIngestBaseUrl?: string;
  send: (callback: AgentCallback) => Promise<boolean>;
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
    logger: options.logger,
  });
}
