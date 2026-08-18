import {
  type Context,
  ROOT_CONTEXT,
  type Span,
  SpanKind,
  SpanStatusCode,
  type Tracer,
  trace,
} from "@opentelemetry/api";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import type { Resource } from "@opentelemetry/resources";
import {
  BasicTracerProvider,
  BatchSpanProcessor,
} from "@opentelemetry/sdk-trace-base";
import { POSTHOG_NOTIFICATIONS } from "./acp-extensions";
import {
  type Attributes,
  asRecord,
  asString,
  DEFAULT_FLUSH_INTERVAL_MS,
  EXPORT_TIMEOUT_MS,
  entryTime,
  normalizeMethod,
  strAttr,
  usageAttributes,
} from "./otel-attributes";
import type { StoredNotification } from "./types";

export interface RunTraceBuilderConfig {
  /** Full OTLP traces endpoint URL, e.g. "https://us.i.posthog.com/i/v1/traces" */
  url: string;
  /** Project API key sent as a Bearer token */
  token: string;
  /** Batch flush interval in ms (default: 2000) */
  flushIntervalMs?: number;
}

/**
 * Builds one APM trace per run from the session notification stream: a root
 * `task_run` span, a child `turn` span per prompt/turn, and a child
 * `tool_call:<kind>` span per tool call. `handle()` returns the OTel context
 * the corresponding log record should be emitted under, so logs and spans
 * cross-link in the UI via trace_id/span_id.
 *
 * Root span status is resolved at shutdown from the LATEST turn outcome (the
 * root span only exports when it ends, so earlier turns must not leave a
 * sticky OK): OK when the last turn ended cleanly (`end_turn`, or an explicit
 * task_complete), ERROR on a run error (which always wins) or a last turn
 * that stopped with `error`, unset otherwise (cancelled / refused / timed out
 * / no completed turns).
 *
 * Spans carry the same allowlist stance as the log export: lifecycle, status,
 * usage, and identifiers only — never prompts, tool arguments, or output.
 */
export class RunTraceBuilder {
  private provider: BasicTracerProvider;
  private tracer: Tracer;
  private rootSpan: Span;
  private rootContext: Context;
  private rootErrored = false;
  /** stopReason of the most recent completed turn; drives root status at shutdown */
  private lastStopReason?: string;
  private turnSpan?: Span;
  private turnContext?: Context;
  private turnIndex = 0;
  private toolSpans = new Map<string, { span: Span; context: Context }>();
  private ended = false;

  constructor(config: RunTraceBuilderConfig, resource: Resource) {
    const exporter = new OTLPTraceExporter({
      url: config.url,
      headers: { Authorization: `Bearer ${config.token}` },
    });

    this.provider = new BasicTracerProvider({
      resource,
      spanProcessors: [
        new BatchSpanProcessor(exporter, {
          scheduledDelayMillis:
            config.flushIntervalMs ?? DEFAULT_FLUSH_INTERVAL_MS,
          exportTimeoutMillis: EXPORT_TIMEOUT_MS,
        }),
      ],
    });

    this.tracer = this.provider.getTracer("agent-session");
    this.rootSpan = this.tracer.startSpan("task_run", {
      kind: SpanKind.SERVER,
    });
    this.rootContext = trace.setSpan(ROOT_CONTEXT, this.rootSpan);
  }

  /**
   * Advances the span state machine with one stored entry and returns the
   * context the entry's log record (if any) should attach to.
   */
  handle(entry: StoredNotification): Context {
    if (this.ended) return this.rootContext;
    const rawMethod = entry.notification.method;
    if (typeof rawMethod !== "string") return this.currentContext();
    const method = normalizeMethod(rawMethod);
    const params = asRecord(entry.notification.params) ?? {};
    const time = entryTime(entry.timestamp);

    switch (method) {
      // The ACP prompt request is what starts a turn; its content never leaves
      // the sandbox — it is only a turn boundary marker here.
      case "session/prompt":
        return this.startTurn(time);
      case POSTHOG_NOTIFICATIONS.TURN_COMPLETE:
        return this.endTurn(params, time);
      case POSTHOG_NOTIFICATIONS.USAGE_UPDATE: {
        (this.turnSpan ?? this.rootSpan).setAttributes(usageAttributes(params));
        return this.currentContext();
      }
      case POSTHOG_NOTIFICATIONS.TASK_COMPLETE:
        // Explicit success signal (forward-compat; production decides the
        // terminal status outside the sandbox) — treated as a clean outcome.
        this.lastStopReason = "end_turn";
        return this.rootContext;
      case POSTHOG_NOTIFICATIONS.ERROR:
        return this.handleError(params, time);
      case "session/update":
        return this.handleSessionUpdate(params, time);
      default:
        return this.currentContext();
    }
  }

  async flush(): Promise<void> {
    await this.provider.forceFlush();
  }

  /**
   * Ends any open spans (status unset), resolves the root status from the
   * latest turn outcome, then flushes and stops the provider.
   */
  async shutdown(): Promise<void> {
    if (this.ended) return;
    this.ended = true;
    const now = new Date();
    this.closeOpenTools(now);
    this.closeTurn(undefined, now);
    if (!this.rootErrored) {
      if (this.lastStopReason === "end_turn") {
        this.rootSpan.setStatus({ code: SpanStatusCode.OK });
      } else if (this.lastStopReason === "error") {
        this.rootSpan.setStatus({ code: SpanStatusCode.ERROR });
      }
      // Any other latest outcome (cancelled, refusal, max_tokens, none)
      // leaves the status unset: neither success nor failure.
    }
    this.rootSpan.end(now);
    await this.provider.shutdown();
  }

  private currentContext(): Context {
    return this.turnContext ?? this.rootContext;
  }

  private startTurn(time: Date): Context {
    // A new prompt while a turn is still open means we missed its completion;
    // close it without a status rather than nesting turns.
    this.closeOpenTools(time);
    this.closeTurn(undefined, time);
    this.turnIndex += 1;
    this.turnSpan = this.tracer.startSpan(
      "turn",
      {
        kind: SpanKind.INTERNAL,
        startTime: time,
        attributes: { turn_index: this.turnIndex },
      },
      this.rootContext,
    );
    this.turnContext = trace.setSpan(this.rootContext, this.turnSpan);
    return this.turnContext;
  }

  private endTurn(params: Record<string, unknown>, time: Date): Context {
    const context = this.turnContext ?? this.rootContext;
    const stopReason = asString(params.stopReason);
    this.closeOpenTools(time);
    this.closeTurn({ stopReason, errored: stopReason === "error" }, time);
    // The sandbox never emits task_complete for successful runs (the terminal
    // "completed" status is decided by the workflow outside), so the latest
    // turn outcome is the run's success signal — recorded here, resolved into
    // the root span status at shutdown so an early clean turn can't leave a
    // stale OK on a run whose last turn was cancelled.
    this.lastStopReason = stopReason;
    return context;
  }

  private closeTurn(
    end: { stopReason?: string; errored?: boolean } | undefined,
    time: Date,
  ): void {
    if (!this.turnSpan) return;
    if (end?.stopReason) {
      this.turnSpan.setAttribute("stop_reason", end.stopReason);
    }
    if (end) {
      this.turnSpan.setStatus({
        code: end.errored ? SpanStatusCode.ERROR : SpanStatusCode.OK,
      });
    }
    this.turnSpan.end(time);
    this.turnSpan = undefined;
    this.turnContext = undefined;
  }

  private handleSessionUpdate(
    params: Record<string, unknown>,
    time: Date,
  ): Context {
    const update = asRecord(params.update);
    const updateType = update?.sessionUpdate;
    if (!update || typeof updateType !== "string") {
      return this.currentContext();
    }
    if (updateType === "tool_call") return this.startTool(update, time);
    if (updateType === "tool_call_update") {
      return this.handleToolUpdate(update, time);
    }
    if (updateType === "usage_update") {
      (this.turnSpan ?? this.rootSpan).setAttributes(usageAttributes(update));
    }
    return this.currentContext();
  }

  private startTool(update: Record<string, unknown>, time: Date): Context {
    const toolCallId = asString(update.toolCallId);
    const existing = toolCallId ? this.toolSpans.get(toolCallId) : undefined;
    if (existing) return existing.context;

    const kind = asString(update.kind) ?? "unknown";
    const parentContext = this.turnContext ?? this.rootContext;
    const attributes: Attributes = { tool_kind: kind };
    if (toolCallId) attributes.tool_call_id = toolCallId;

    const span = this.tracer.startSpan(
      // Kind (read/edit/execute/...) is a small enum, so per-kind span names
      // stay low-cardinality and make APM latency breakdowns useful.
      `tool_call:${kind}`,
      { kind: SpanKind.INTERNAL, startTime: time, attributes },
      parentContext,
    );
    const context = trace.setSpan(parentContext, span);
    if (toolCallId) {
      this.toolSpans.set(toolCallId, { span, context });
    } else {
      // Without an id there is no terminal update to match; record a marker.
      span.end(time);
    }
    return context;
  }

  private handleToolUpdate(
    update: Record<string, unknown>,
    time: Date,
  ): Context {
    const toolCallId = asString(update.toolCallId);
    const open = toolCallId ? this.toolSpans.get(toolCallId) : undefined;
    if (!open || !toolCallId) return this.currentContext();

    const status = update.status;
    if (status === "completed" || status === "failed") {
      open.span.setAttribute("tool_status", status);
      open.span.setStatus({
        code: status === "failed" ? SpanStatusCode.ERROR : SpanStatusCode.OK,
      });
      open.span.end(time);
      this.toolSpans.delete(toolCallId);
    }
    return open.context;
  }

  private handleError(params: Record<string, unknown>, time: Date): Context {
    this.rootErrored = true;
    this.closeOpenTools(time, { interrupted: true });
    const stopReason = asString(params.stopReason);
    this.closeTurn({ stopReason, errored: true }, time);
    // params.error is free text that can embed prompt or repo content, so
    // only the error's provenance is exported; the raw message stays in the
    // session log and on the task run's error_message.
    const attrs: Attributes = {};
    strAttr(attrs, "error_source", params.source);
    this.rootSpan.setAttributes(attrs);
    this.rootSpan.setStatus({ code: SpanStatusCode.ERROR });
    return this.rootContext;
  }

  /**
   * Ends every open tool span. Interrupted (a run error aborted the tool
   * mid-flight) marks them errored so APM doesn't show a healthy-looking
   * active tool under a failed run; otherwise the outcome is unknown and the
   * status stays unset.
   */
  private closeOpenTools(time: Date, opts?: { interrupted?: boolean }): void {
    for (const { span } of this.toolSpans.values()) {
      if (opts?.interrupted) {
        span.setAttribute("tool_status", "interrupted");
        span.setStatus({ code: SpanStatusCode.ERROR });
      }
      span.end(time);
    }
    this.toolSpans.clear();
  }
}
