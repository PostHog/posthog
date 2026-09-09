import {
  type SketchpadPresenceInput,
  type SketchpadStreamEvent,
  sketchpadLogEntrySchema,
  sketchpadPresenceSchema,
  sleepWithBackoff,
} from "@posthog/shared";
import { inject, injectable } from "inversify";
import {
  PROJECT_API_CLIENT,
  type ProjectApiClient,
} from "../canvas/projectApiClient";
import type { ISketchpadStreamService } from "./identifiers";
import { logEntryInput, sketchpadPath } from "./sketchpadService";

const RECONNECT_INITIAL_MS = 500;
const RECONNECT_MAX_MS = 10_000;
const MAX_FRAME_BYTES = 512 * 1024;

interface SseFrame {
  id?: string;
  event: string;
  data: string;
}

function toLogEntry(data: unknown): SketchpadStreamEvent | null {
  const parsed = sketchpadLogEntrySchema.safeParse(logEntryInput(data));
  return parsed.success ? { type: "op", entry: parsed.data } : null;
}

function toPresence(data: unknown): SketchpadStreamEvent | null {
  if (typeof data !== "object" || data === null) return null;
  const row = data as Record<string, unknown>;
  const parsed = sketchpadPresenceSchema.safeParse({
    clientId: row.client_id,
    cursor: row.cursor ?? null,
    viewport: row.viewport ?? null,
    selectedIds: row.selected_ids ?? [],
    carets: row.carets ?? [],
    userId: row.user_id ?? undefined,
    userUuid: row.user_uuid ?? undefined,
    userName: row.user_name ?? undefined,
    userEmail: row.user_email ?? undefined,
  });
  return parsed.success ? { type: "presence", presence: parsed.data } : null;
}

function toStreamEvent(frame: SseFrame): SketchpadStreamEvent | null {
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
        throw new Error("Sketchpad stream frame is too large");
      }
    }
  } finally {
    reader.cancel().catch(() => {});
  }
}

function presenceBody(input: SketchpadPresenceInput): string {
  return JSON.stringify({
    client_id: input.clientId,
    cursor: input.cursor,
    viewport: input.viewport,
    selected_ids: input.selectedIds,
    carets: input.carets,
  });
}

@injectable()
export class SketchpadStreamService implements ISketchpadStreamService {
  constructor(
    @inject(PROJECT_API_CLIENT)
    private readonly api: ProjectApiClient,
  ) {}

  async *streamSketchpad(
    sketchpadId: string,
    signal?: AbortSignal,
  ): AsyncGenerator<SketchpadStreamEvent> {
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
        const res = await this.api.fetch(
          `${sketchpadPath(sketchpadId)}stream/`,
          {
            headers,
            signal: stop,
          },
        );
        if (!res.ok || !res.body) {
          throw new Error(`Sketchpad stream refused (${res.status})`);
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
      await sleepWithBackoff(
        attempt,
        {
          initialDelayMs: RECONNECT_INITIAL_MS,
          maxDelayMs: RECONNECT_MAX_MS,
        },
        stop,
      );
      attempt += 1;
    }
  }

  async sendPresence(
    sketchpadId: string,
    input: SketchpadPresenceInput,
  ): Promise<void> {
    const res = await this.api.fetch(`${sketchpadPath(sketchpadId)}presence/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: presenceBody(input),
      signal: AbortSignal.timeout(5_000),
    });
    if (!res.ok && res.status !== 429) {
      throw new Error(`Failed to send presence (${res.status})`);
    }
  }
}
