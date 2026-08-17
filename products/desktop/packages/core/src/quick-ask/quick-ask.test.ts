import { describe, expect, it, vi } from "vitest";
import type { AuthService } from "../auth/auth";
import {
  parseSseChunk,
  type QuickAskEvent,
  QuickAskService,
  reasoningLabel,
  translateFrame,
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

function openResponse(taskId = "task-1", runId = "run-1"): Response {
  return new Response(
    JSON.stringify({ task_id: taskId, run_id: runId, run_status: "queued" }),
    { status: 200 },
  );
}

function notification(method: string, params: unknown): string {
  return JSON.stringify({
    type: "notification",
    notification: { method, params },
  });
}

function sessionUpdate(update: unknown): string {
  return notification("session/update", { update });
}

function agentText(text: string): string {
  return sessionUpdate({
    sessionUpdate: "agent_message_chunk",
    content: { type: "text", text },
  });
}

const USER_ECHO = sessionUpdate({
  sessionUpdate: "user_message_chunk",
  content: { type: "text", text: "how many signups?" },
});
const TURN_COMPLETE = notification("_posthog/turn_complete", {});

interface MockedAuth {
  service: QuickAskService;
  fetchMock: ReturnType<typeof vi.fn>;
}

interface MockRoutes {
  /** Responses for `/open/` POSTs, consumed in order. */
  open?: Response[];
  /** Responses for `/stream/` GETs, consumed in order. */
  stream?: Response[];
  channels?: Response;
  patch?: Response;
}

/**
 * URL-routed fetch mock: the channel-filing calls run detached from the ask
 * generator, so a strictly ordered response queue would be racy.
 */
function serviceWith(routes: MockRoutes): MockedAuth {
  const open = [...(routes.open ?? [])];
  const stream = [...(routes.stream ?? [])];
  const fetchMock = vi.fn(
    async (_fetch: unknown, url: string): Promise<Response> => {
      if (url.endsWith("/open/")) {
        return open.shift() ?? new Response("exhausted", { status: 500 });
      }
      if (url.includes("/stream/")) {
        return stream.shift() ?? new Response("exhausted", { status: 500 });
      }
      if (url.includes("/task_channels/")) {
        return routes.channels ?? new Response("nope", { status: 404 });
      }
      return routes.patch ?? new Response("{}", { status: 200 });
    },
  );
  const authService = {
    getValidAccessToken: vi.fn().mockResolvedValue({
      accessToken: "t",
      apiHost: "https://us.posthog.com",
    }),
    getState: vi.fn().mockReturnValue({ currentProjectId: 2 }),
    authenticatedFetch: fetchMock,
  } as unknown as AuthService;
  return { service: new QuickAskService(authService), fetchMock };
}

async function collect(
  service: QuickAskService,
  question = "how many signups?",
  conversationId?: string,
): Promise<QuickAskEvent[]> {
  const events: QuickAskEvent[] = [];
  for await (const event of service.ask({ question, conversationId })) {
    if (event.type !== "trace") {
      events.push(event);
    }
  }
  return events;
}

describe("QuickAskService", () => {
  it("parses SSE blocks into event/id/data frames", () => {
    const blocks = [
      ...parseSseChunk(
        'id: 1-0\ndata: {"a":1}\n\nevent: stream-end\ndata: {"status":"complete"}',
      ),
    ];
    expect(blocks).toEqual([
      { event: "message", id: "1-0", data: '{"a":1}' },
      {
        event: "stream-end",
        id: undefined,
        data: '{"status":"complete"}',
      },
    ]);
  });

  it("streams a turn: echo gate, growing text snapshots, turn complete", async () => {
    const stream = sseResponse([
      // Boot noise before the user's echo is skipped.
      `id: 1-0\ndata: ${notification("_posthog/console", { message: "boot" })}\n\n`,
      `id: 2-0\ndata: ${USER_ECHO}\n\nid: 3-0\ndata: ${agentText("Signups are ")}\n\n`,
      // A frame split across two network reads.
      `id: 4-0\ndata: ${agentText("up 12%.")}`.slice(0, 40),
      `${`id: 4-0\ndata: ${agentText("up 12%.")}`.slice(40)}\n\nid: 5-0\ndata: ${TURN_COMPLETE}\n\n`,
    ]);
    const { service } = serviceWith({
      open: [openResponse()],
      stream: [stream],
    });
    await expect(collect(service)).resolves.toEqual([
      { type: "conversation", conversationId: expect.any(String) },
      { type: "text", id: "turn-1", content: "Signups are ", complete: false },
      {
        type: "text",
        id: "turn-1",
        content: "Signups are up 12%.",
        complete: false,
      },
      {
        type: "text",
        id: "turn-1",
        content: "Signups are up 12%.",
        complete: true,
      },
      { type: "done" },
    ]);
  });

  it("sends the steering block on the first turn only, after the question", async () => {
    const { service, fetchMock } = serviceWith({
      open: [openResponse(), openResponse()],
      stream: [
        sseResponse([`data: ${USER_ECHO}\n\ndata: ${TURN_COMPLETE}\n\n`]),
        sseResponse([`data: ${USER_ECHO}\n\ndata: ${TURN_COMPLETE}\n\n`]),
      ],
    });
    const first = await collect(service);
    const conversationId = (first[0] as { conversationId: string })
      .conversationId;
    await collect(service, "and yesterday?", conversationId);

    const firstBody = JSON.parse(fetchMock.mock.calls[0][2].body as string);
    // The question leads (it becomes the task title); steering follows.
    expect(firstBody.content).toMatch(
      /^how many signups\?\n\n<posthog_trusted_context>/,
    );
    expect(firstBody.content).toContain('<hogql display="block"');
    expect(fetchMock.mock.calls[0][1]).toContain(
      `/conversations/${conversationId}/open/`,
    );
    const openCalls = fetchMock.mock.calls.filter((call) =>
      String(call[1]).endsWith("/open/"),
    );
    const followUpBody = JSON.parse(openCalls[1]?.[2].body as string);
    expect(followUpBody.content).toBe("and yesterday?");
  });

  it("files the task into the personal channel once, best-effort", async () => {
    const channels = new Response(
      JSON.stringify([
        { id: "chan-pub", channel_type: "public" },
        { id: "chan-me", channel_type: "personal" },
      ]),
      { status: 200 },
    );
    const { service, fetchMock } = serviceWith({
      open: [openResponse(), openResponse()],
      stream: [
        sseResponse([`data: ${USER_ECHO}\n\ndata: ${TURN_COMPLETE}\n\n`]),
        sseResponse([`data: ${USER_ECHO}\n\ndata: ${TURN_COMPLETE}\n\n`]),
      ],
      channels,
    });
    const first = await collect(service);
    const conversationId = (first[0] as { conversationId: string })
      .conversationId;
    // The filing fetches run detached from the ask generator.
    await vi.waitFor(() => {
      const patch = fetchMock.mock.calls.find(
        (call) => call[2]?.method === "PATCH",
      );
      expect(patch).toBeDefined();
      expect(patch?.[1]).toContain("/tasks/task-1/");
      expect(JSON.parse(patch?.[2].body as string)).toEqual({
        channel: "chan-me",
      });
    });
    await collect(service, "and yesterday?", conversationId);
    const patches = fetchMock.mock.calls.filter(
      (call) => call[2]?.method === "PATCH",
    );
    expect(patches).toHaveLength(1);
  });

  it("separates agent messages around a tool call and surfaces tool labels", async () => {
    const stream = sseResponse([
      `data: ${USER_ECHO}\n\n`,
      `data: ${agentText("Checking.")}\n\n`,
      `data: ${sessionUpdate({ sessionUpdate: "tool_call", title: "execute-sql" })}\n\n`,
      `data: ${agentText("1,204 signups this week.")}\n\n`,
      `data: ${TURN_COMPLETE}\n\n`,
    ]);
    const { service } = serviceWith({
      open: [openResponse()],
      stream: [stream],
    });
    const events = await collect(service);
    expect(events).toContainEqual({
      type: "reasoning",
      content: "Running execute-sql…",
    });
    expect(events).toContainEqual({
      type: "text",
      id: "turn-1",
      content: "Checking.\n\n1,204 signups this week.",
      complete: true,
    });
  });

  it("shows the latest thought line as the reasoning label", async () => {
    const stream = sseResponse([
      `data: ${USER_ECHO}\n\n`,
      `data: ${sessionUpdate({ sessionUpdate: "agent_thought_chunk", content: { type: "text", text: "Looking at signups\nby day" } })}\n\n`,
      `data: ${TURN_COMPLETE}\n\n`,
    ]);
    const { service } = serviceWith({
      open: [openResponse()],
      stream: [stream],
    });
    const events = await collect(service);
    expect(events).toContainEqual({ type: "reasoning", content: "by day" });
  });

  it("resumes across a stream rotation with the last event id", async () => {
    const first = sseResponse([
      `id: 7-0\ndata: ${USER_ECHO}\n\nevent: end\ndata: {"type":"rotated"}\n\n`,
    ]);
    const second = sseResponse([
      `id: 8-0\ndata: ${agentText("Done.")}\n\nid: 9-0\ndata: ${TURN_COMPLETE}\n\n`,
    ]);
    const { service, fetchMock } = serviceWith({
      open: [openResponse()],
      stream: [first, second],
    });
    const events = await collect(service);
    expect(events).toContainEqual({
      type: "text",
      id: "turn-1",
      content: "Done.",
      complete: true,
    });
    const streamCalls = fetchMock.mock.calls.filter((call) =>
      String(call[1]).includes("/stream/"),
    );
    expect(streamCalls).toHaveLength(2);
    expect(streamCalls[1][2].headers["Last-Event-ID"]).toBe("7-0");
  });

  it("ends the turn when the run reaches a terminal status", async () => {
    const stream = sseResponse([
      `data: ${USER_ECHO}\n\ndata: ${agentText("Partial answer.")}\n\n`,
      `data: ${JSON.stringify({ type: "task_run_state", status: "completed" })}\n\n`,
    ]);
    const { service } = serviceWith({
      open: [openResponse()],
      stream: [stream],
    });
    const events = await collect(service);
    expect(events.at(-1)).toEqual({ type: "done" });
  });

  it("surfaces a failed run as an error", async () => {
    const stream = sseResponse([
      `data: ${USER_ECHO}\n\n`,
      `data: ${JSON.stringify({ type: "task_run_state", status: "failed", error_message: "sandbox died" })}\n\n`,
    ]);
    const { service } = serviceWith({
      open: [openResponse()],
      stream: [stream],
    });
    const events = await collect(service);
    expect(events.at(-1)).toEqual({
      type: "error",
      message: "PostHog AI hit an error. Try asking again.",
      detail: "sandbox died",
    });
  });

  it("maps open failures: quota, flag off, and everything else", async () => {
    const cases: [number, string][] = [
      [402, "You are out of PostHog AI credits."],
      [400, "PostHog AI tasks are not enabled for this project."],
      [503, "PostHog AI is unavailable right now (503)."],
    ];
    for (const [status, message] of cases) {
      const { service } = serviceWith({
        open: [new Response("nope", { status })],
      });
      const events = await collect(service);
      expect(events[1]).toEqual({
        type: "error",
        message,
        detail: "nope",
      });
    }
  });

  it("never calls the API when signed out", async () => {
    const fetchMock = vi.fn();
    const authService = {
      getValidAccessToken: vi
        .fn()
        .mockResolvedValue({ accessToken: "t", apiHost: "https://x" }),
      getState: vi.fn().mockReturnValue({ currentProjectId: null }),
      authenticatedFetch: fetchMock,
    } as unknown as AuthService;
    const service = new QuickAskService(authService);
    const events = await collect(service);
    expect(events).toEqual([
      { type: "error", message: "Sign in to PostHog to ask questions." },
    ]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("warm stores the run handle and the next ask reuses the conversation", async () => {
    const { service, fetchMock } = serviceWith({
      open: [openResponse("task-w", "run-w"), openResponse("task-w", "run-w")],
      stream: [
        sseResponse([`data: ${USER_ECHO}\n\ndata: ${TURN_COMPLETE}\n\n`]),
      ],
    });
    await service.warm();
    const warmBody = JSON.parse(fetchMock.mock.calls[0][2].body as string);
    expect(warmBody).toEqual({});
    const events = await collect(service);
    expect(events.at(-1)).toEqual({ type: "done" });
    // Both open calls target the same client-minted conversation id.
    expect(fetchMock.mock.calls[1][1]).toBe(fetchMock.mock.calls[0][1]);
  });

  it("warm failures are swallowed", async () => {
    const { service } = serviceWith({
      open: [new Response("boom", { status: 500 })],
    });
    await expect(service.warm()).resolves.toBeUndefined();
  });

  it("reset drops the session so the next ask starts a new conversation", async () => {
    const { service, fetchMock } = serviceWith({
      open: [openResponse(), openResponse("task-2", "run-2")],
      stream: [
        sseResponse([`data: ${USER_ECHO}\n\ndata: ${TURN_COMPLETE}\n\n`]),
        sseResponse([`data: ${USER_ECHO}\n\ndata: ${TURN_COMPLETE}\n\n`]),
      ],
    });
    await collect(service);
    service.reset();
    await collect(service);
    const openCalls = fetchMock.mock.calls.filter((call) =>
      String(call[1]).endsWith("/open/"),
    );
    expect(openCalls[0][1]).not.toBe(openCalls[1][1]);
    // A fresh conversation carries the steering block again.
    const secondBody = JSON.parse(openCalls[1][2].body as string);
    expect(secondBody.content).toContain("<posthog_trusted_context>");
  });
});

describe("translateFrame", () => {
  it.each([
    ["agent text", agentText("hi"), { kind: "agent-text", text: "hi" }],
    ["user echo", USER_ECHO, { kind: "user-echo" }],
    ["turn complete", TURN_COMPLETE, { kind: "turn-complete" }],
    [
      "tool call falls back to claudeCode tool name",
      sessionUpdate({
        sessionUpdate: "tool_call",
        _meta: { claudeCode: { toolName: "Bash" } },
      }),
      { kind: "tool", label: "Bash" },
    ],
    [
      "posthog error",
      notification("_posthog/error", { message: "crash" }),
      { kind: "run-terminal", status: "failed", errorMessage: "crash" },
    ],
    [
      "non-terminal run state",
      JSON.stringify({ type: "task_run_state", status: "in_progress" }),
      { kind: "ignore", detail: "run state in_progress" },
    ],
    [
      "keepalive frame",
      JSON.stringify({ type: "keepalive" }),
      { kind: "ignore" },
    ],
  ])("%s", (_name, frame, expected) => {
    expect(translateFrame(JSON.parse(frame))).toEqual(expected);
  });
});

describe("reasoningLabel", () => {
  it("returns the last non-empty line", () => {
    expect(reasoningLabel("Analyzing signups\n\nby weekday ")).toBe(
      "by weekday",
    );
    expect(reasoningLabel("")).toBe("");
  });
});
