import { inject, injectable } from "inversify";
import type { AuthService } from "../auth/auth";
import { AUTH_SERVICE } from "../auth/auth.module";

export const QUICK_ASK_SERVICE = Symbol.for("posthog.core.quickAsk.service");

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
  | { type: "viz" }
  | { type: "error"; message: string }
  | { type: "done" };

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
}

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

function toEvents(event: string, data: string): QuickAskEvent[] {
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
    case "ai/multi_viz":
      return [{ type: "viz" }];
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
      return [];
  }
}

/**
 * Streams one PostHog AI turn for the quick-ask panel. Business logic only:
 * auth, project resolution, the SSE request, and translation into
 * `QuickAskEvent`s. The host forwards events over IPC.
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

    const response = await this.authService.authenticatedFetch(
      fetch,
      `${apiHost}/api/environments/${projectId}/conversations/`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: input.question,
          ...(input.conversationId
            ? { conversation: input.conversationId }
            : {}),
          trace_id: globalThis.crypto.randomUUID(),
        }),
        signal: controller.signal,
      },
    );

    if (!response.ok || !response.body) {
      yield {
        type: "error",
        message:
          response.status === 402
            ? "You are out of PostHog AI credits."
            : `PostHog AI is unavailable right now (${response.status}).`,
      };
      return;
    }

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
          for (const quickAskEvent of toEvents(event, data)) {
            yield quickAskEvent;
          }
        }
      }
      for (const { event, data } of parseSseChunk(buffer)) {
        for (const quickAskEvent of toEvents(event, data)) {
          yield quickAskEvent;
        }
      }
      yield { type: "done" };
    } finally {
      if (this.controller === controller) {
        this.controller = null;
      }
    }
  }
}
