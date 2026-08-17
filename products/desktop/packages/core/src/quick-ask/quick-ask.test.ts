import { describe, expect, it, vi } from "vitest";
import type { AuthService } from "../auth/auth";
import {
  parseSseChunk,
  type QuickAskEvent,
  QuickAskService,
} from "./quick-ask";

function sseResponse(frames: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const frame of frames) {
        controller.enqueue(encoder.encode(frame));
      }
      controller.close();
    },
  });
  return new Response(body, { status: 200 });
}

function serviceWith(response: Response): QuickAskService {
  const authService = {
    getValidAccessToken: vi.fn().mockResolvedValue({
      accessToken: "t",
      apiHost: "https://us.posthog.com",
    }),
    getState: vi.fn().mockReturnValue({ currentProjectId: 2 }),
    authenticatedFetch: vi.fn().mockResolvedValue(response),
  } as unknown as AuthService;
  return new QuickAskService(authService);
}

async function collect(service: QuickAskService): Promise<QuickAskEvent[]> {
  const events: QuickAskEvent[] = [];
  for await (const event of service.ask({ question: "how many signups?" })) {
    events.push(event);
  }
  return events;
}

describe("QuickAskService", () => {
  it("parses multi-line SSE blocks into event/data pairs", () => {
    const blocks = [
      ...parseSseChunk(
        'event: conversation\ndata: {"id":"c1"}\n\nevent: message\ndata: {"type":"ai"}',
      ),
    ];
    expect(blocks).toEqual([
      { event: "conversation", data: '{"id":"c1"}' },
      { event: "message", data: '{"type":"ai"}' },
    ]);
  });

  it("translates a streamed turn, including an SSE frame split across reads", () => {
    // The `temp-` snapshot grows across chunks; the id-bearing final message
    // replaces it. The second frame is split mid-JSON across two reads.
    const frames = [
      'event: conversation\ndata: {"id":"c1"}\n\nevent: message\ndata: {"type":"ai","id":"temp-1","content":"Sign"}\n\nevent: message\ndata: {"type":"ai","id":"tem',
      'p-1","content":"Signups are up"}\n\nevent: message\ndata: {"type":"ai","id":"m1","content":"Signups are up 12%."}\n\n',
    ];
    return expect(collect(serviceWith(sseResponse(frames)))).resolves.toEqual([
      { type: "conversation", conversationId: "c1" },
      { type: "text", id: "temp-1", content: "Sign", complete: false },
      {
        type: "text",
        id: "temp-1",
        content: "Signups are up",
        complete: false,
      },
      {
        type: "text",
        id: "m1",
        content: "Signups are up 12%.",
        complete: true,
      },
      { type: "done" },
    ]);
  });

  it("maps a viz message and a failure message", async () => {
    const frames = [
      'event: message\ndata: {"type":"ai/viz","id":"v1"}\n\nevent: message\ndata: {"type":"ai/failure","content":"Rate limited"}\n\n',
    ];
    const events = await collect(serviceWith(sseResponse(frames)));
    expect(events).toEqual([
      { type: "viz" },
      { type: "error", message: "Rate limited" },
      { type: "done" },
    ]);
  });

  it("yields a sign-in error without calling the API when no project is selected", async () => {
    const authService = {
      getValidAccessToken: vi.fn().mockResolvedValue({
        accessToken: "t",
        apiHost: "https://us.posthog.com",
      }),
      getState: vi.fn().mockReturnValue({ currentProjectId: null }),
      authenticatedFetch: vi.fn(),
    } as unknown as AuthService;
    const service = new QuickAskService(authService);
    const events: QuickAskEvent[] = [];
    for await (const event of service.ask({ question: "hi" })) {
      events.push(event);
    }
    expect(events).toEqual([
      { type: "error", message: "Sign in to PostHog to ask questions." },
    ]);
    expect(
      (
        authService as unknown as {
          authenticatedFetch: ReturnType<typeof vi.fn>;
        }
      ).authenticatedFetch,
    ).not.toHaveBeenCalled();
  });
});
