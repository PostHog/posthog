import {
  type SketchpadPresenceInput,
  type SketchpadStreamEvent,
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

import { type SseEvent, SseEventParser } from "../cloud-task/sse-parser";

function toLogEntry(data: unknown): SketchpadStreamEvent | null {
  try {
    return { type: "op", entry: logEntryInput(data) };
  } catch {
    return null;
  }
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

function toStreamEvent(frame: SseEvent): SketchpadStreamEvent | null {
  const data = frame.data;
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

async function* readFrames(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<SseEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseEventParser(undefined, MAX_FRAME_BYTES);
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      yield* parser.parse(decoder.decode(chunk.value, { stream: true }));
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
