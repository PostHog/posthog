import {
  type CanvasV2PresenceInput,
  type CanvasV2StreamEvent,
  canvasV2LogEntrySchema,
  canvasV2PresenceSchema,
  getBackoffDelay,
} from "@posthog/shared";
import { inject, injectable } from "inversify";
import {
  PROJECT_API_CLIENT,
  type ProjectApiClient,
} from "../canvas/projectApiClient";
import type { ICanvasV2StreamService } from "./identifiers";

const RECONNECT_INITIAL_MS = 500;
const RECONNECT_MAX_MS = 10_000;
/** One frame cannot grow past this, so a stuck stream cannot eat memory. */
const MAX_FRAME_BYTES = 512 * 1024;

interface SseFrame {
  id?: string;
  event: string;
  data: string;
}

function boardPath(id: string): string {
  return `canvas_boards/${encodeURIComponent(id)}/`;
}

function actorInput(actor: Record<string, unknown>): unknown {
  return {
    kind: actor.kind,
    userId: actor.user_id ?? undefined,
    userName: actor.user_name ?? undefined,
    taskId: actor.task_id ?? undefined,
  };
}

function toLogEntry(data: unknown): CanvasV2StreamEvent | null {
  if (typeof data !== "object" || data === null) return null;
  const row = data as Record<string, unknown>;
  const actor = row.actor;
  const parsed = canvasV2LogEntrySchema.safeParse({
    seq: row.seq,
    opId: row.op_id,
    actor:
      typeof actor === "object" && actor !== null
        ? actorInput(actor as Record<string, unknown>)
        : actor,
    createdAt: row.created_at,
    op: row.op,
  });
  return parsed.success ? { type: "op", entry: parsed.data } : null;
}

function toPresence(data: unknown): CanvasV2StreamEvent | null {
  if (typeof data !== "object" || data === null) return null;
  const row = data as Record<string, unknown>;
  const parsed = canvasV2PresenceSchema.safeParse({
    clientId: row.client_id,
    cursor: row.cursor ?? null,
    viewport: row.viewport ?? null,
    selectedIds: row.selected_ids ?? [],
    userId: row.user_id ?? undefined,
    userName: row.user_name ?? undefined,
  });
  return parsed.success ? { type: "presence", presence: parsed.data } : null;
}

function toStreamEvent(frame: SseFrame): CanvasV2StreamEvent | null {
  let data: unknown;
  try {
    data = frame.data.length > 0 ? JSON.parse(frame.data) : null;
  } catch {
    return null;
  }
  switch (frame.event) {
    case "op":
      return toLogEntry(data);
    case "presence":
      return toPresence(data);
    case "reload": {
      const since = (data as { since?: unknown } | null)?.since;
      return { type: "reload", since: typeof since === "number" ? since : 0 };
    }
    case "error": {
      const detail = (data as { error?: unknown } | null)?.error;
      return {
        type: "error",
        message:
          typeof detail === "string" ? detail.slice(0, 500) : "Stream error",
      };
    }
    default:
      return null;
  }
}

function parseFrame(raw: string): SseFrame | null {
  let id: string | undefined;
  let event = "message";
  const dataLines: string[] = [];
  for (const line of raw.split("\n")) {
    if (line.length === 0 || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
    if (field === "id") id = value;
    else if (field === "event") event = value;
    else if (field === "data") dataLines.push(value);
  }
  if (dataLines.length === 0 && id === undefined) return null;
  return { id, event, data: dataLines.join("\n") };
}

/** Server-sent-event frames of one response body. */
async function* readFrames(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<SseFrame> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      buffer = buffer.replace(/\r\n/g, "\n");
      let split = buffer.indexOf("\n\n");
      while (split !== -1) {
        const frame = parseFrame(buffer.slice(0, split));
        buffer = buffer.slice(split + 2);
        if (frame) yield frame;
        split = buffer.indexOf("\n\n");
      }
      if (buffer.length > MAX_FRAME_BYTES) {
        throw new Error("Board stream frame is too large");
      }
    }
  } finally {
    reader.cancel().catch(() => {});
  }
}

function delay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        resolve();
      },
      { once: true },
    );
  });
}

function presenceBody(input: CanvasV2PresenceInput): string {
  return JSON.stringify({
    client_id: input.clientId,
    cursor: input.cursor,
    viewport: input.viewport,
    selected_ids: input.selectedIds,
  });
}

/**
 * The live board stream. The project token lives in the host, and a browser
 * `EventSource` cannot set a header, so the host holds the connection and the
 * renderer reads it over a tRPC subscription.
 */
@injectable()
export class CanvasV2StreamService implements ICanvasV2StreamService {
  constructor(
    @inject(PROJECT_API_CLIENT)
    private readonly api: ProjectApiClient,
  ) {}

  async *streamBoard(
    boardId: string,
    signal?: AbortSignal,
  ): AsyncGenerator<CanvasV2StreamEvent> {
    const stop = signal ?? new AbortController().signal;
    let lastEventId: string | undefined;
    let attempt = 0;

    while (!stop.aborted) {
      let opened = false;
      try {
        const headers: Record<string, string> = {
          Accept: "text/event-stream",
        };
        if (lastEventId !== undefined) headers["Last-Event-ID"] = lastEventId;
        const res = await this.api.fetch(`${boardPath(boardId)}stream/`, {
          headers,
          signal: stop,
        });
        if (!res.ok || !res.body) {
          throw new Error(`Board stream refused (${res.status})`);
        }
        opened = true;
        attempt = 0;
        yield { type: "live", live: true };
        for await (const frame of readFrames(res.body)) {
          if (frame.id !== undefined && frame.id.length > 0) {
            lastEventId = frame.id;
          }
          const event = toStreamEvent(frame);
          if (event) yield event;
        }
      } catch (error) {
        if (stop.aborted) break;
        yield {
          type: "error",
          message: error instanceof Error ? error.message : String(error),
        };
      }
      if (opened) yield { type: "live", live: false };
      if (stop.aborted) break;
      // The server closes an idle stream after five minutes, so the first
      // reconnect must be quick and only repeated failures back off.
      await delay(
        getBackoffDelay(attempt, {
          initialDelayMs: RECONNECT_INITIAL_MS,
          maxDelayMs: RECONNECT_MAX_MS,
        }),
        stop,
      );
      attempt += 1;
    }
  }

  async sendPresence(
    boardId: string,
    input: CanvasV2PresenceInput,
  ): Promise<void> {
    const res = await this.api.fetch(`${boardPath(boardId)}presence/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: presenceBody(input),
      signal: AbortSignal.timeout(5_000),
    });
    // A throttled ping is not a failure: the next one carries the position.
    if (!res.ok && res.status !== 429) {
      throw new Error(`Failed to send presence (${res.status})`);
    }
  }
}
