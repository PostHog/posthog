import { SeverityNumber } from "@opentelemetry/api-logs";
import { OTLPLogExporter } from "@opentelemetry/exporter-logs-otlp-http";
import { resourceFromAttributes } from "@opentelemetry/resources";
import {
  BatchLogRecordProcessor,
  LoggerProvider,
} from "@opentelemetry/sdk-logs";
import {
  ATTR_SERVICE_NAME,
  ATTR_SERVICE_VERSION,
} from "@opentelemetry/semantic-conventions";
import { POSTHOG_NOTIFICATIONS } from "./acp-extensions";
import {
  type Attributes,
  asRecord,
  asString,
  DEFAULT_FLUSH_INTERVAL_MS,
  EXPORT_TIMEOUT_MS,
  entryTime,
  MAX_BODY_CHARS,
  normalizeMethod,
  strAttr,
  truncate,
  usageAttributes,
} from "./otel-attributes";
import { RunTraceBuilder } from "./otel-trace-builder";
import type { SessionLogSink } from "./session-log-writer";
import type { StoredNotification } from "./types";
import type { Logger } from "./utils/logger";

const SERVICE_NAME = "posthog-code-agent";

export interface OtelTelemetryConfig {
  /** Full OTLP logs endpoint URL, e.g. "https://us.i.posthog.com/i/v1/logs" */
  url: string;
  /** Project API key sent as a Bearer token */
  token: string;
  /** Full OTLP traces endpoint URL; spans are off when unset */
  tracesUrl?: string;
  /** Batch flush interval in ms (default: 2000) */
  flushIntervalMs?: number;
}

/**
 * Session identity pinned as OTel resource attributes. Resource attributes are
 * indexed via resource_fingerprint in PostHog Logs, so runs are directly
 * filterable per user/task/run in the Logs UI.
 */
export interface OtelSessionResource {
  /** Parent task grouping - all runs for a task share this */
  taskId: string;
  /** Primary conversation identifier - all events in a run share this */
  runId: string;
  /** Deployment environment - "local" for desktop, "cloud" for cloud sandbox */
  deviceType: "local" | "cloud";
  teamId?: number;
  userId?: number;
  distinctId?: string;
  /** Runtime adapter: "claude" or "codex" */
  adapter?: string;
  /** Run mode: "interactive" or "background" */
  mode?: string;
  agentVersion?: string;
}

export interface MappedLogRecord {
  severityNumber: SeverityNumber;
  severityText: string;
  body: string;
  attributes: Attributes;
}

function record(
  severity: [SeverityNumber, string],
  body: string,
  eventType: string,
  attributes: Attributes = {},
): MappedLogRecord {
  return {
    severityNumber: severity[0],
    severityText: severity[1],
    body: truncate(body, MAX_BODY_CHARS),
    attributes: { event_type: eventType, ...attributes },
  };
}

const INFO: [SeverityNumber, string] = [SeverityNumber.INFO, "INFO"];
const WARN: [SeverityNumber, string] = [SeverityNumber.WARN, "WARN"];
const ERROR: [SeverityNumber, string] = [SeverityNumber.ERROR, "ERROR"];

function mapSessionUpdate(
  method: string,
  params: Record<string, unknown>,
): MappedLogRecord | null {
  const update = asRecord(params.update);
  const updateType = update?.sessionUpdate;
  if (!update || typeof updateType !== "string") return null;

  switch (updateType) {
    case "tool_call": {
      const attrs: Attributes = { session_update_type: updateType };
      strAttr(attrs, "tool_call_id", update.toolCallId);
      const kind = strAttr(attrs, "tool_kind", update.kind);
      strAttr(attrs, "tool_status", update.status ?? "pending");
      return record(
        INFO,
        `tool call started${kind ? ` (${kind})` : ""}`,
        method,
        attrs,
      );
    }
    case "tool_call_update": {
      const status = update.status;
      // In-progress snapshots re-send the growing tool input/output; only the
      // terminal transition is run metadata.
      if (status !== "completed" && status !== "failed") return null;
      const attrs: Attributes = { session_update_type: updateType };
      strAttr(attrs, "tool_call_id", update.toolCallId);
      strAttr(attrs, "tool_status", status);
      return record(
        status === "failed" ? WARN : INFO,
        `tool call ${status}`,
        method,
        attrs,
      );
    }
    case "usage_update":
      return record(INFO, "usage update", method, {
        session_update_type: updateType,
        ...usageAttributes(update),
      });
    default:
      return null;
  }
}

/**
 * Maps a stored session notification to an exportable log record, or null for
 * notification types that must not leave the sandbox.
 *
 * Allowlist by design: agent message/thought text, tool arguments, and tool
 * output stay in the session log (the product source of truth) - only
 * run-lifecycle metadata is exported, so prompts and repo content never reach
 * the telemetry project.
 */
export function mapNotificationToLogRecord(
  entry: StoredNotification,
): MappedLogRecord | null {
  const rawMethod = entry.notification.method;
  if (typeof rawMethod !== "string") return null;
  const method = normalizeMethod(rawMethod);
  const params = asRecord(entry.notification.params) ?? {};

  if (method === "session/update") {
    return mapSessionUpdate(method, params);
  }

  switch (method) {
    case POSTHOG_NOTIFICATIONS.RUN_STARTED: {
      const attrs: Attributes = {};
      strAttr(attrs, "agent_version", params.agentVersion);
      strAttr(attrs, "session_id", params.sessionId);
      return record(INFO, "run started", method, attrs);
    }
    case POSTHOG_NOTIFICATIONS.SDK_SESSION: {
      const attrs: Attributes = {};
      const adapter = strAttr(attrs, "adapter", params.adapter);
      strAttr(attrs, "session_id", params.sessionId);
      return record(
        INFO,
        `sdk session created${adapter ? ` (${adapter})` : ""}`,
        method,
        attrs,
      );
    }
    case POSTHOG_NOTIFICATIONS.USAGE_UPDATE:
      return record(INFO, "usage update", method, usageAttributes(params));
    case POSTHOG_NOTIFICATIONS.TURN_COMPLETE: {
      const attrs: Attributes = {};
      const stopReason = strAttr(attrs, "stop_reason", params.stopReason);
      return record(
        INFO,
        `turn complete${stopReason ? ` (${stopReason})` : ""}`,
        method,
        attrs,
      );
    }
    case POSTHOG_NOTIFICATIONS.TASK_COMPLETE: {
      const attrs: Attributes = {};
      strAttr(attrs, "stop_reason", params.stopReason);
      return record(INFO, "task complete", method, attrs);
    }
    case POSTHOG_NOTIFICATIONS.ERROR: {
      // params.error is free text that can embed prompt or repo content
      // (exception messages, provider errors), so only its provenance is
      // exported. The raw message stays in the session log and on the task
      // run's error_message.
      const attrs: Attributes = {};
      strAttr(attrs, "error_source", params.source);
      strAttr(attrs, "stop_reason", params.stopReason);
      return record(ERROR, "run error", method, attrs);
    }
    // POSTHOG_NOTIFICATIONS.CONSOLE is deliberately NOT exported: those are
    // free-text agent-server diagnostics that interpolate arbitrary data
    // (prompt previews, stringified extension params), so shipping them would
    // leak content the allowlist exists to keep in the sandbox. They remain
    // in the S3 session log and the event-ingest stream.
    case POSTHOG_NOTIFICATIONS.PROGRESS: {
      const attrs: Attributes = {};
      strAttr(attrs, "progress_group", params.group);
      const step = strAttr(attrs, "progress_step", params.step);
      const status = strAttr(attrs, "progress_status", params.status);
      const label = asString(params.label);
      return record(
        INFO,
        `progress: ${step ?? "step"} ${status ?? ""}${label ? ` (${label})` : ""}`.trim(),
        method,
        attrs,
      );
    }
    case POSTHOG_NOTIFICATIONS.GIT_CHECKPOINT: {
      const attrs: Attributes = {};
      strAttr(attrs, "branch", params.branch);
      return record(INFO, "git checkpoint", method, attrs);
    }
    case POSTHOG_NOTIFICATIONS.BRANCH_CREATED: {
      const attrs: Attributes = {};
      strAttr(attrs, "branch", params.branch ?? params.branchName);
      return record(INFO, "branch created", method, attrs);
    }
    case POSTHOG_NOTIFICATIONS.MODE_CHANGE: {
      const attrs: Attributes = {};
      strAttr(attrs, "run_mode", params.mode);
      return record(INFO, "mode change", method, attrs);
    }
    case POSTHOG_NOTIFICATIONS.COMPACT_BOUNDARY:
      return record(INFO, "compact boundary", method, {});
    case POSTHOG_NOTIFICATIONS.PERMISSION_REQUEST:
    case POSTHOG_NOTIFICATIONS.PERMISSION_RESPONSE:
    case POSTHOG_NOTIFICATIONS.PERMISSION_RESOLVED: {
      // params.toolCall/options carry tool content; export identifiers only.
      const attrs: Attributes = {};
      strAttr(attrs, "request_id", params.requestId);
      strAttr(attrs, "tool_call_id", params.toolCallId);
      const action = method.slice(method.indexOf("/") + 1).replace("_", " ");
      return record(INFO, action, method, attrs);
    }
    default:
      return null;
  }
}

/**
 * Ships run telemetry to PostHog over OTLP: an allowlisted metadata subset of
 * the session log to PostHog Logs (see mapNotificationToLogRecord) and, when a
 * traces URL is configured, an APM trace per run (see RunTraceBuilder) with
 * trace/span ids stamped on the log records so the two cross-link in the UI.
 * Registered as a SessionLogWriter sink; the S3 session log remains the source
 * of truth for the full transcript.
 */
export class OtelRunTelemetry implements SessionLogSink {
  private loggerProvider: LoggerProvider;
  private otelLogger: ReturnType<LoggerProvider["getLogger"]>;
  private traceBuilder?: RunTraceBuilder;
  private runId: string;
  private debugLogger?: Logger;
  private shutdownStarted = false;

  constructor(
    config: OtelTelemetryConfig,
    resource: OtelSessionResource,
    debugLogger?: Logger,
  ) {
    this.runId = resource.runId;
    this.debugLogger = debugLogger;

    const exporter = new OTLPLogExporter({
      url: config.url,
      headers: { Authorization: `Bearer ${config.token}` },
    });

    const processor = new BatchLogRecordProcessor(exporter, {
      scheduledDelayMillis: config.flushIntervalMs ?? DEFAULT_FLUSH_INTERVAL_MS,
      exportTimeoutMillis: EXPORT_TIMEOUT_MS,
    });

    const resourceAttributes: Attributes = {
      [ATTR_SERVICE_NAME]: SERVICE_NAME,
    };
    strAttr(resourceAttributes, ATTR_SERVICE_VERSION, resource.agentVersion);
    strAttr(resourceAttributes, "run_id", resource.runId);
    strAttr(resourceAttributes, "task_id", resource.taskId);
    strAttr(resourceAttributes, "device_type", resource.deviceType);
    strAttr(resourceAttributes, "team_id", resource.teamId?.toString());
    strAttr(resourceAttributes, "user_id", resource.userId?.toString());
    strAttr(resourceAttributes, "distinct_id", resource.distinctId);
    strAttr(resourceAttributes, "adapter", resource.adapter);
    strAttr(resourceAttributes, "run_mode", resource.mode);

    const otelResource = resourceFromAttributes(resourceAttributes);

    this.loggerProvider = new LoggerProvider({
      resource: otelResource,
      processors: [processor],
    });

    this.otelLogger = this.loggerProvider.getLogger("agent-session");

    if (config.tracesUrl) {
      this.traceBuilder = new RunTraceBuilder(
        {
          url: config.tracesUrl,
          token: config.token,
          flushIntervalMs: config.flushIntervalMs,
        },
        otelResource,
      );
    }
  }

  append(sessionId: string, entry: StoredNotification): void {
    // Resource attributes pin this writer to one run; ignore entries for any
    // other session so records are never mislabeled.
    if (sessionId !== this.runId || this.shutdownStarted) return;
    try {
      // The span state machine must see every entry: e.g. session/prompt is a
      // turn boundary even though it never becomes a log record.
      const context = this.traceBuilder?.handle(entry);
      const mapped = mapNotificationToLogRecord(entry);
      if (!mapped) return;
      this.otelLogger.emit({
        ...mapped,
        timestamp: entryTime(entry.timestamp),
        context,
      });
    } catch (error) {
      // Telemetry must never interfere with the run.
      this.debugLogger?.debug("Failed to emit OTel telemetry", { error });
    }
  }

  /**
   * Best-effort: logs and traces flush independently, so a rejecting or
   * hanging traces endpoint can never block or fail the log flush (and vice
   * versa). Never rejects.
   */
  async flush(): Promise<void> {
    await Promise.allSettled([
      this.loggerProvider.forceFlush(),
      this.traceBuilder?.flush(),
    ]);
  }

  /**
   * Ends open spans, flushes batched records, then stops the providers.
   * Idempotent and best-effort: the two providers shut down independently
   * and a failure in one never skips the other. Never rejects.
   */
  async shutdown(): Promise<void> {
    if (this.shutdownStarted) return;
    this.shutdownStarted = true;
    await Promise.allSettled([
      this.traceBuilder?.shutdown(),
      this.loggerProvider.shutdown(),
    ]);
  }
}
