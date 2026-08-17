import { describe, expect, it, vi } from "vitest";
import type { AuthService } from "../auth/auth";
import {
  parseSseChunk,
  type QuickAskEvent,
  QuickAskService,
  toChart,
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
      // Minted client-side before the request, then confirmed by the server.
      { type: "conversation", conversationId: expect.any(String) },
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

  it("always sends a conversation UUID in the request body", async () => {
    // The API rejects requests without one (400): `conversation` is required
    // and is how new conversations are created.
    const response = sseResponse(["event: message\ndata: {}\n\n"]);
    const service = serviceWith(response);
    await collect(service);
    const fetchMock = (
      service as unknown as {
        authService: { authenticatedFetch: ReturnType<typeof vi.fn> };
      }
    ).authService.authenticatedFetch;
    const body = JSON.parse(fetchMock.mock.calls[0][2].body as string);
    expect(body.conversation).toMatch(/^[0-9a-f-]{36}$/);
    expect(body.content).toBe("how many signups?");
  });

  it("maps a viz message and a failure message", async () => {
    const frames = [
      'event: message\ndata: {"type":"ai/viz","id":"v1"}\n\nevent: message\ndata: {"type":"ai/failure","content":"Rate limited"}\n\n',
    ];
    const events = await collect(serviceWith(sseResponse(frames)));
    expect(events).toEqual([
      { type: "conversation", conversationId: expect.any(String) },
      { type: "viz" },
      { type: "error", message: "Rate limited" },
      { type: "done" },
    ]);
  });

  it("runs a viz query and emits a drawable chart", async () => {
    const query = {
      kind: "TrendsQuery",
      trendsFilter: { display: "ActionsLineGraph" },
    };
    const sse = sseResponse([
      `event: message\ndata: ${JSON.stringify({ type: "ai/viz", id: "v1", answer: query })}\n\n`,
    ]);
    const queryResponse = new Response(
      JSON.stringify({
        results: [
          {
            label: "signups",
            data: [1, 2, 3],
            days: ["2026-08-01", "2026-08-02", "2026-08-03"],
          },
        ],
      }),
      { status: 200 },
    );
    const service = serviceWith(sse);
    const fetchMock = (
      service as unknown as {
        authService: { authenticatedFetch: ReturnType<typeof vi.fn> };
      }
    ).authService.authenticatedFetch;
    fetchMock.mockResolvedValueOnce(sse).mockResolvedValueOnce(queryResponse);
    const events = await collect(service);
    expect(events).toEqual([
      { type: "conversation", conversationId: expect.any(String) },
      { type: "trace", detail: "viz query collected (ai/viz)" },
      {
        type: "chart",
        chart: {
          kind: "line",
          title: "signups",
          labels: ["8/1", "8/2", "8/3"],
          series: [{ name: "signups", points: [1, 2, 3] }],
        },
      },
      { type: "done" },
    ]);
    // The chart request went to the query endpoint with the viz's query AST.
    expect(fetchMock.mock.calls[1][1]).toContain("/query/");
    expect(JSON.parse(fetchMock.mock.calls[1][2].body as string).query).toEqual(
      query,
    );
  });

  it("falls back to the viz note for query kinds the panel cannot draw", async () => {
    const sse = sseResponse([
      `event: message\ndata: ${JSON.stringify({ type: "ai/viz", id: "v1", answer: { kind: "FunnelsQuery" } })}\n\n`,
    ]);
    const events = await collect(serviceWith(sse));
    expect(events).toEqual([
      { type: "conversation", conversationId: expect.any(String) },
      { type: "trace", detail: "viz query collected (ai/viz)" },
      { type: "viz", reason: "query kind FunnelsQuery is not drawable" },
      { type: "done" },
    ]);
  });

  it("collects viz queries from the artifact messages agent mode emits", async () => {
    const query = {
      kind: "TrendsQuery",
      trendsFilter: { display: "ActionsBar" },
    };
    const artifact = {
      type: "ai/artifact",
      id: "a1",
      artifact_id: "a1",
      content: {
        content_type: "visualization",
        query,
        name: "Daily active users",
      },
    };
    const sse = sseResponse([
      `event: message\ndata: ${JSON.stringify(artifact)}\n\n`,
    ]);
    const queryResponse = new Response(
      JSON.stringify({
        results: [
          { label: "DAU", data: [4, 5], days: ["2026-08-01", "2026-08-02"] },
        ],
      }),
      { status: 200 },
    );
    const service = serviceWith(sse);
    const fetchMock = (
      service as unknown as {
        authService: { authenticatedFetch: ReturnType<typeof vi.fn> };
      }
    ).authService.authenticatedFetch;
    fetchMock.mockResolvedValueOnce(sse).mockResolvedValueOnce(queryResponse);
    const events = await collect(service);
    expect(events).toEqual([
      { type: "conversation", conversationId: expect.any(String) },
      { type: "trace", detail: "viz query collected (ai/artifact)" },
      {
        type: "chart",
        chart: {
          kind: "bar",
          title: "Daily active users",
          labels: ["8/1", "8/2"],
          series: [{ name: "DAU", points: [4, 5] }],
        },
      },
      { type: "done" },
    ]);
  });

  it("maps bar display types and non-ISO labels through toChart", () => {
    const chart = toChart(
      { kind: "TrendsQuery", trendsFilter: { display: "ActionsBar" } },
      [{ label: "WAU", data: [5, 6], labels: ["W31", "W32"] }],
    );
    expect(chart).toEqual({
      kind: "bar",
      title: "WAU",
      labels: ["W31", "W32"],
      series: [{ name: "WAU", points: [5, 6] }],
    });
    expect(toChart({ kind: "HogQLQuery" }, [])).toBeNull();
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
