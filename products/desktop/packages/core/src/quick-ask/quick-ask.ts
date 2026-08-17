import { inject, injectable } from "inversify";
import type { AuthService } from "../auth/auth";
import { AUTH_SERVICE } from "../auth/auth.module";

export const QUICK_ASK_SERVICE = Symbol.for("posthog.core.quickAsk.service");

/** A compact chart the panel can draw: series over shared x-axis labels. */
export interface QuickAskChart {
  kind: "line" | "bar";
  title: string;
  labels: string[];
  series: { name: string; points: number[] }[];
}

/**
 * Events the quick-ask panel renders, distilled from the PostHog AI
 * conversations SSE stream (the same protocol the web app's Max parses in
 * `maxThreadLogic`). Message events arrive as growing snapshots keyed by id;
 * the service forwards them as-is and the renderer replaces by id.
 */
export type QuickAskEvent =
  | { type: "conversation"; conversationId: string }
  | { type: "reasoning"; content: string }
  | { type: "text"; id: string; content: string; complete: boolean }
  | { type: "chart"; chart: QuickAskChart }
  /** The answer has a visualization the panel could not render. */
  | { type: "viz"; reason?: string }
  | { type: "error"; message: string; detail?: string }
  | { type: "done" }
  | { type: "trace"; detail: string };

export interface QuickAskInput {
  question: string;
  /** Continues an existing thread; omitted for the first question. */
  conversationId?: string;
}

interface AssistantSseMessage {
  type?: string;
  id?: string;
  content?: unknown;
  status?: string;
  answer?: unknown;
  visualizations?: { answer?: unknown }[];
}

interface AssistantArtifactContent {
  content_type?: unknown;
  query?: unknown;
  name?: unknown;
}

interface AssistantQuery {
  kind?: string;
  trendsFilter?: { display?: string };
  series?: { custom_name?: string; name?: string; event?: string }[];
}

interface QueryResponseSeries {
  label?: string;
  data?: number[];
  labels?: string[];
  days?: string[];
  action?: { name?: string };
}

/** Query kinds whose results share the trends series shape the panel can draw. */
const CHARTABLE_QUERY_KINDS = new Set([
  "TrendsQuery",
  "LifecycleQuery",
  "StickinessQuery",
]);
const MAX_CHART_SERIES = 3;
const MAX_CHARTS = 2;

/** Minimal SSE parser: collects `event:`/`data:` lines per blank-line-delimited block. */
export function* parseSseChunk(
  buffer: string,
): Generator<{ event: string; data: string }> {
  for (const block of buffer.split("\n\n")) {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) {
        event = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    }
    if (dataLines.length > 0) {
      yield { event, data: dataLines.join("\n") };
    }
  }
}

interface StreamCollector {
  /** Query ASTs from viz messages, run after the stream to render charts. */
  vizQueries: { query: unknown; title?: string }[];
}

function toEvents(
  event: string,
  data: string,
  collector: StreamCollector,
): QuickAskEvent[] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    return [];
  }
  if (event === "conversation") {
    const conversation = parsed as { id?: string };
    return conversation.id
      ? [{ type: "conversation", conversationId: conversation.id }]
      : [];
  }
  if (event !== "message") {
    return [];
  }
  const message = parsed as AssistantSseMessage;
  switch (message.type) {
    case "ai": {
      if (typeof message.content !== "string") {
        return [];
      }
      // In-progress snapshots stream with a `temp-` id (or none); the final
      // message arrives once with a real id (mirrors maxThreadLogic).
      const complete = message.id != null && !message.id.startsWith("temp-");
      return [
        {
          type: "text",
          id: message.id ?? "pending",
          content: message.content,
          complete,
        },
      ];
    }
    case "ai/reasoning":
      return typeof message.content === "string"
        ? [{ type: "reasoning", content: message.content }]
        : [];
    case "ai/viz":
      if (message.answer != null) {
        collector.vizQueries.push({ query: message.answer });
        return [{ type: "trace", detail: "viz query collected (ai/viz)" }];
      }
      return [{ type: "viz" }];
    case "ai/multi_viz": {
      const answers = (message.visualizations ?? [])
        .map((item) => item.answer)
        .filter((answer) => answer != null);
      if (answers.length > 0) {
        collector.vizQueries.push(...answers.map((query) => ({ query })));
        return [
          { type: "trace", detail: "viz query collected (ai/multi_viz)" },
        ];
      }
      return [{ type: "viz" }];
    }
    // Agent mode emits visualizations as artifacts; the query AST is inline.
    case "ai/artifact": {
      const content = message.content as AssistantArtifactContent | undefined;
      if (content?.content_type === "visualization" && content.query != null) {
        collector.vizQueries.push({
          query: content.query,
          title: typeof content.name === "string" ? content.name : undefined,
        });
        return [{ type: "trace", detail: "viz query collected (ai/artifact)" }];
      }
      return [
        {
          type: "trace",
          detail: `artifact ignored (${String(content?.content_type)})`,
        },
      ];
    }
    case "ai/failure":
      return [
        {
          type: "error",
          message:
            typeof message.content === "string" && message.content
              ? message.content
              : "Something went wrong. Try again.",
        },
      ];
    default:
      return message.type
        ? [
            {
              type: "trace",
              detail: `stream message ignored (${message.type})`,
            },
          ]
        : [];
  }
}

function seriesName(result: QueryResponseSeries, index: number): string {
  return result.label ?? result.action?.name ?? `Series ${index + 1}`;
}

/** Shortens ISO dates ("2026-08-14") to "8/14" for the x-axis. */
function shortLabel(label: string): string {
  const isoMatch = label.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (isoMatch) {
    return `${Number(isoMatch[2])}/${Number(isoMatch[3])}`;
  }
  return label;
}

export function toChart(
  query: unknown,
  results: unknown,
  title?: string,
): QuickAskChart | null {
  const assistantQuery = query as AssistantQuery;
  if (!CHARTABLE_QUERY_KINDS.has(assistantQuery.kind ?? "")) {
    return null;
  }
  if (!Array.isArray(results) || results.length === 0) {
    return null;
  }
  const seriesResults = (results as QueryResponseSeries[])
    .filter((result) => Array.isArray(result.data))
    .slice(0, MAX_CHART_SERIES);
  if (seriesResults.length === 0) {
    return null;
  }
  const first = seriesResults[0];
  const labels = (first.days ?? first.labels ?? []).map(shortLabel);
  const display = assistantQuery.trendsFilter?.display ?? "";
  return {
    kind: display.includes("Bar") ? "bar" : "line",
    title: title ?? seriesResults.map(seriesName).join(" · "),
    labels,
    series: seriesResults.map((result, index) => ({
      name: seriesName(result, index),
      points: result.data ?? [],
    })),
  };
}

/**
 * Streams one PostHog AI turn for the quick-ask panel. Business logic only:
 * auth, project resolution, the SSE request, translation into
 * `QuickAskEvent`s, and running viz queries into drawable charts. The host
 * forwards events over IPC.
 */
@injectable()
export class QuickAskService {
  private controller: AbortController | null = null;

  constructor(
    @inject(AUTH_SERVICE)
    private readonly authService: AuthService,
  ) {}

  cancel(): void {
    this.controller?.abort();
    this.controller = null;
  }

  private async runQueryToChart(
    apiHost: string,
    projectId: number,
    entry: { query: unknown; title?: string },
    signal: AbortSignal,
  ): Promise<QuickAskChart | null> {
    const assistantQuery = entry.query as AssistantQuery;
    const kind = assistantQuery.kind ?? "unknown";
    if (!CHARTABLE_QUERY_KINDS.has(kind)) {
      throw new Error(`query kind ${kind} is not drawable`);
    }
    const response = await this.authService.authenticatedFetch(
      fetch,
      `${apiHost}/api/environments/${projectId}/query/`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: entry.query, refresh: "blocking" }),
        signal,
      },
    );
    if (!response.ok) {
      const detail = await response
        .text()
        .then((text) => text.slice(0, 200))
        .catch(() => "");
      throw new Error(`query failed with ${response.status}: ${detail}`);
    }
    const payload = (await response.json()) as { results?: unknown };
    return toChart(entry.query, payload.results, entry.title);
  }

  async *ask(input: QuickAskInput): AsyncGenerator<QuickAskEvent> {
    this.cancel();
    const controller = new AbortController();
    this.controller = controller;

    const { apiHost } = await this.authService.getValidAccessToken();
    const projectId = this.authService.getState().currentProjectId;
    if (projectId == null) {
      yield { type: "error", message: "Sign in to PostHog to ask questions." };
      return;
    }

    // The API requires a client-minted conversation id on every request; it
    // retrieves the existing conversation or creates a new one from it.
    const conversationId =
      input.conversationId ?? globalThis.crypto.randomUUID();
    yield { type: "conversation", conversationId };

    const response = await this.authService.authenticatedFetch(
      fetch,
      `${apiHost}/api/environments/${projectId}/conversations/`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: input.question,
          conversation: conversationId,
          trace_id: globalThis.crypto.randomUUID(),
        }),
        signal: controller.signal,
      },
    );

    if (!response.ok || !response.body) {
      const detail = await response
        .text()
        .then((text) => text.slice(0, 500))
        .catch(() => "");
      yield {
        type: "error",
        message:
          response.status === 402
            ? "You are out of PostHog AI credits."
            : `PostHog AI is unavailable right now (${response.status}).`,
        detail,
      };
      return;
    }

    const collector: StreamCollector = { vizQueries: [] };
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // Process complete SSE blocks; keep the trailing partial block.
        const lastDelimiter = buffer.lastIndexOf("\n\n");
        if (lastDelimiter === -1) continue;
        const complete = buffer.slice(0, lastDelimiter);
        buffer = buffer.slice(lastDelimiter + 2);
        for (const { event, data } of parseSseChunk(complete)) {
          for (const quickAskEvent of toEvents(event, data, collector)) {
            yield quickAskEvent;
          }
        }
      }
      for (const { event, data } of parseSseChunk(buffer)) {
        for (const quickAskEvent of toEvents(event, data, collector)) {
          yield quickAskEvent;
        }
      }

      // Turn viz queries into drawable charts; anything unrenderable falls
      // back to the "open in PostHog" note.
      let chartRendered = false;
      let chartFailure: string | null = null;
      for (const entry of collector.vizQueries.slice(0, MAX_CHARTS)) {
        try {
          const chart = await this.runQueryToChart(
            apiHost,
            projectId,
            entry,
            controller.signal,
          );
          if (chart) {
            yield { type: "chart", chart };
            chartRendered = true;
          } else {
            chartFailure ??= `results for ${(entry.query as AssistantQuery).kind ?? "unknown"} had no drawable series`;
          }
        } catch (error) {
          chartFailure ??=
            error instanceof Error ? error.message : "chart query failed";
        }
      }
      if (collector.vizQueries.length > 0 && !chartRendered) {
        yield { type: "viz", reason: chartFailure ?? undefined };
      }

      yield { type: "done" };
    } finally {
      if (this.controller === controller) {
        this.controller = null;
      }
    }
  }
}
