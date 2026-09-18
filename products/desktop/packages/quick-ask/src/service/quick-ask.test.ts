import type { AuthService } from "@posthog/core/auth/auth";
import { describe, expect, it, vi } from "vitest";
import {
  PANEL_STEERING,
  parseSseChunk,
  type QuickAskEvent,
  type QuickAskRunDefaults,
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

function taskResponse(
  taskId = "task-1",
  runId: string | null = "run-1",
): Response {
  return new Response(
    JSON.stringify({
      id: taskId,
      latest_run: runId ? { id: runId, status: "in_progress" } : null,
    }),
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

/** The complete-snapshot frame ACP sends to close a run of chunks. */
function agentMessage(text: string): string {
  return sessionUpdate({
    sessionUpdate: "agent_message",
    content: { type: "text", text },
  });
}

function promptEcho(text: string): string {
  return notification("session/prompt", {
    prompt: [{ type: "text", text }],
  });
}

const QUESTION = "how many signups?";
const FIRST_TURN_CONTENT = `${QUESTION}\n\n${PANEL_STEERING}`;
/** Echo of the first question as the run logs it (question + steering). */
const USER_ECHO = promptEcho(FIRST_TURN_CONTENT);
const TURN_COMPLETE = notification("_posthog/turn_complete", {});
const SIMPLE_TURN = [`data: ${USER_ECHO}\n\ndata: ${TURN_COMPLETE}\n\n`];

interface MockedAuth {
  service: QuickAskService;
  fetchMock: ReturnType<typeof vi.fn>;
  s3Mock: ReturnType<typeof vi.fn>;
}

interface MockRoutes {
  /** Responses for `POST /tasks/warm/`, consumed in order. */
  warm?: Response[];
  /** Responses for `POST /tasks/`, consumed in order. */
  createTask?: Response[];
  /** Responses for `POST .../runs/` (run creation), consumed in order. */
  createRun?: Response[];
  /** Responses for `POST .../runs/{id}/start/`, consumed in order. */
  startRun?: Response[];
  /** Responses for `POST .../runs/{id}/command/`, consumed in order. */
  command?: Response[];
  /** Responses for `GET .../stream/`, consumed in order. */
  stream?: Response[];
  /** Responses for `POST .../prepare_upload/`, consumed in order. */
  prepare?: Response[];
  /** Responses for `POST .../finalize_upload/`, consumed in order. */
  finalize?: Response[];
}

/** URL-routed fetch mock - the warm call runs detached from ask generators. */
function serviceWith(
  routes: MockRoutes,
  runDefaults?: () => QuickAskRunDefaults,
): MockedAuth {
  const queues = {
    warm: [...(routes.warm ?? [])],
    createTask: [...(routes.createTask ?? [])],
    createRun: [...(routes.createRun ?? [])],
    startRun: [...(routes.startRun ?? [])],
    command: [...(routes.command ?? [])],
    stream: [...(routes.stream ?? [])],
    prepare: [...(routes.prepare ?? [])],
    finalize: [...(routes.finalize ?? [])],
  };
  const route = (url: string): keyof typeof queues => {
    if (url.endsWith("/tasks/warm/")) return "warm";
    if (url.endsWith("/tasks/")) return "createTask";
    if (url.endsWith("/runs/")) return "createRun";
    if (url.endsWith("/start/")) return "startRun";
    if (url.endsWith("/command/")) return "command";
    if (url.includes("/stream/")) return "stream";
    if (url.endsWith("/prepare_upload/")) return "prepare";
    if (url.endsWith("/finalize_upload/")) return "finalize";
    throw new Error(`unrouted url: ${url}`);
  };
  const fetchMock = vi.fn(
    async (_fetch: unknown, url: string): Promise<Response> => {
      return (
        queues[route(url)].shift() ?? new Response("exhausted", { status: 500 })
      );
    },
  );
  // Presigned S3 uploads bypass authenticatedFetch.
  const s3Mock = vi.fn(
    async (): Promise<Response> => new Response(null, { status: 204 }),
  );
  const authService = {
    getValidAccessToken: vi.fn().mockResolvedValue({
      accessToken: "t",
      apiHost: "https://us.posthog.com",
    }),
    getState: vi.fn().mockReturnValue({ currentProjectId: 2 }),
    authenticatedFetch: fetchMock,
  } as unknown as AuthService;
  return {
    service: new QuickAskService(
      authService,
      s3Mock as unknown as typeof fetch,
      runDefaults,
    ),
    fetchMock,
    s3Mock,
  };
}

function preparedResponse(ids: string[]): Response {
  return new Response(
    JSON.stringify({
      artifacts: ids.map((id) => ({
        id,
        presigned_post: { url: "https://s3.local/upload", fields: { k: "v" } },
      })),
    }),
    { status: 200 },
  );
}

const SHOT = {
  name: "screenshot.png",
  base64: btoa("png-bytes"),
  mimeType: "image/png",
};

function callsTo(fetchMock: ReturnType<typeof vi.fn>, suffix: string) {
  return fetchMock.mock.calls.filter((call) =>
    String(call[1]).endsWith(suffix),
  );
}

async function collect(
  service: QuickAskService,
  question = "how many signups?",
  conversationId?: string,
  attachments?: { name: string; base64: string; mimeType: string }[],
): Promise<QuickAskEvent[]> {
  const events: QuickAskEvent[] = [];
  for await (const event of service.ask({
    question,
    conversationId,
    attachments,
  })) {
    events.push(event);
  }
  return events;
}

function conversationIdOf(events: QuickAskEvent[]): string {
  const event = events[0];
  if (event.type !== "conversation") throw new Error("no conversation event");
  return event.conversationId;
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
      createTask: [taskResponse()],
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

  it("a closing agent_message replaces its chunks instead of duplicating them", async () => {
    const stream = sseResponse([
      `id: 1-0\ndata: ${USER_ECHO}\n\n` +
        `id: 2-0\ndata: ${agentText("Signups are ")}\n\n` +
        `id: 3-0\ndata: ${agentText("up 12%.")}\n\n` +
        // ACP closes the message with the full snapshot, not another delta.
        `id: 4-0\ndata: ${agentMessage("Signups are up 12%.")}\n\n` +
        `id: 5-0\ndata: ${TURN_COMPLETE}\n\n`,
    ]);
    const { service } = serviceWith({
      createTask: [taskResponse()],
      stream: [stream],
    });
    const texts = (await collect(service)).filter((e) => e.type === "text");
    // The snapshot supersedes the chunks; the answer is a single copy, not
    // "Signups are up 12%.Signups are up 12%.".
    expect(texts.at(-1)).toEqual({
      type: "text",
      id: "turn-1",
      content: "Signups are up 12%.",
      complete: true,
    });
  });

  it("cancels the stream reader when the turn ends", async () => {
    let cancelled = false;
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            `data: ${USER_ECHO}\n\ndata: ${agentText("hi")}\n\ndata: ${TURN_COMPLETE}\n\n`,
          ),
        );
        // Left open on purpose: only reader.cancel() should release it, so the
        // spy fires exactly when the turn tears its connection down.
      },
      cancel() {
        cancelled = true;
      },
    });
    const { service } = serviceWith({
      createTask: [taskResponse()],
      stream: [new Response(body, { status: 200 })],
    });
    await collect(service);
    expect(cancelled).toBe(true);
  });

  it("creates the task with the question as description and warm-matching fields", async () => {
    const { service, fetchMock } = serviceWith({
      createTask: [taskResponse()],
      stream: [sseResponse(SIMPLE_TURN)],
    });
    await collect(service);
    const body = JSON.parse(callsTo(fetchMock, "/tasks/")[0][2].body as string);
    // The description becomes the task title; steering rides only the message.
    expect(body.description).toBe("how many signups?");
    expect(body.pending_user_message).toMatch(
      /^how many signups\?\n\n<posthog_trusted_context>/,
    );
    expect(body.pending_user_message).toContain('<hogql display="block"');
    // `branch` present (null) opts into the backend's warm-run lookup; the
    // repo-less shape matches what `warm()` provisioned.
    expect(body).toMatchObject({ branch: null, repositories: [] });
  });

  it("follow-ups ride the command relay without the steering block", async () => {
    const followUpTurn = [
      `data: ${promptEcho("and yesterday?")}\n\ndata: ${TURN_COMPLETE}\n\n`,
    ];
    const { service, fetchMock } = serviceWith({
      createTask: [taskResponse()],
      command: [new Response("{}", { status: 200 })],
      stream: [sseResponse(SIMPLE_TURN), sseResponse(followUpTurn)],
    });
    const first = await collect(service);
    await collect(service, "and yesterday?", conversationIdOf(first));

    const commandCalls = callsTo(fetchMock, "/command/");
    expect(commandCalls).toHaveLength(1);
    expect(commandCalls[0][1]).toContain("/tasks/task-1/runs/run-1/command/");
    const body = JSON.parse(commandCalls[0][2].body as string);
    expect(body.method).toBe("user_message");
    expect(body.params).toEqual({ content: "and yesterday?" });
  });

  it("cold-starts a run when no warm sandbox matched", async () => {
    const { service, fetchMock } = serviceWith({
      createTask: [taskResponse("task-1", null)],
      createRun: [
        new Response(JSON.stringify({ id: "run-9" }), { status: 200 }),
      ],
      startRun: [new Response("{}", { status: 200 })],
      stream: [sseResponse(SIMPLE_TURN)],
    });
    const events = await collect(service);
    expect(events.at(-1)).toEqual({ type: "done" });
    const createRun = JSON.parse(
      callsTo(fetchMock, "/runs/")[0][2].body as string,
    );
    expect(createRun).toMatchObject({
      environment: "cloud",
      mode: "interactive",
      initial_permission_mode: "auto",
    });
    const start = JSON.parse(
      callsTo(fetchMock, "/start/")[0][2].body as string,
    );
    expect(start.pending_user_message).toContain("how many signups?");
    expect(callsTo(fetchMock, "/stream/")[0][1]).toContain("/runs/run-9/");
  });

  it("stages an attachment onto a cold start", async () => {
    const { service, fetchMock, s3Mock } = serviceWith({
      createTask: [taskResponse("task-1", null)],
      prepare: [preparedResponse(["art-1"])],
      finalize: [preparedResponse(["art-1"])],
      createRun: [
        new Response(JSON.stringify({ id: "run-9" }), { status: 200 }),
      ],
      startRun: [new Response("{}", { status: 200 })],
      stream: [sseResponse(SIMPLE_TURN)],
    });
    const events = await collect(service, QUESTION, undefined, [SHOT]);
    expect(events.at(-1)).toEqual({ type: "done" });
    const prepareCall = callsTo(fetchMock, "/prepare_upload/")[0];
    expect(prepareCall[1]).toContain("/tasks/task-1/staged_artifacts/");
    expect(JSON.parse(prepareCall[2].body as string).artifacts[0]).toEqual({
      name: "screenshot.png",
      type: "user_attachment",
      source: "posthog_code",
      size: 9,
      content_type: "image/png",
    });
    expect(s3Mock).toHaveBeenCalledWith(
      "https://s3.local/upload",
      expect.objectContaining({ method: "POST" }),
    );
    const start = JSON.parse(
      callsTo(fetchMock, "/start/")[0][2].body as string,
    );
    expect(start.pending_user_artifact_ids).toEqual(["art-1"]);
  });

  it("uploads an attachment to the warm run before creating the task", async () => {
    const { service, fetchMock } = serviceWith({
      warm: [
        new Response(JSON.stringify({ task_id: "task-w", run_id: "run-w" }), {
          status: 200,
        }),
      ],
      command: [new Response("{}", { status: 200 })],
      prepare: [preparedResponse(["art-1"])],
      finalize: [preparedResponse(["art-1"])],
      createTask: [taskResponse("task-w", "run-w")],
      stream: [sseResponse(SIMPLE_TURN)],
    });
    await service.warm();
    await collect(service, QUESTION, undefined, [SHOT]);
    expect(callsTo(fetchMock, "/prepare_upload/")[0][1]).toContain(
      "/tasks/task-w/runs/run-w/artifacts/",
    );
    const create = JSON.parse(
      callsTo(fetchMock, "/tasks/")[0][2].body as string,
    );
    expect(create.pending_user_artifact_ids).toEqual(["art-1"]);
  });

  it("skips warm reuse and re-stages when the warm upload fails", async () => {
    const { service, fetchMock } = serviceWith({
      warm: [
        new Response(JSON.stringify({ task_id: "task-w", run_id: "run-w" }), {
          status: 200,
        }),
      ],
      command: [new Response("{}", { status: 200 })],
      // The warm-run upload fails; the retry on the cold path succeeds.
      prepare: [
        new Response("nope", { status: 500 }),
        preparedResponse(["art-1"]),
      ],
      finalize: [preparedResponse(["art-1"])],
      createTask: [taskResponse("task-1", null)],
      createRun: [
        new Response(JSON.stringify({ id: "run-9" }), { status: 200 }),
      ],
      startRun: [new Response("{}", { status: 200 })],
      stream: [sseResponse(SIMPLE_TURN)],
    });
    await service.warm();
    const events = await collect(service, QUESTION, undefined, [SHOT]);
    expect(events.at(-1)).toEqual({ type: "done" });
    // No `branch` key: the backend's warm-run lookup must not fire, or the
    // question would ride the warm run without its screenshot.
    const create = JSON.parse(
      callsTo(fetchMock, "/tasks/")[0][2].body as string,
    );
    expect("branch" in create).toBe(false);
    expect(create.pending_user_artifact_ids).toEqual([]);
    // The attachment went up through the fresh task's staged path instead.
    const prepareCalls = callsTo(fetchMock, "/prepare_upload/");
    expect(prepareCalls[1][1]).toContain("/tasks/task-1/staged_artifacts/");
    const start = JSON.parse(
      callsTo(fetchMock, "/start/")[0][2].body as string,
    );
    expect(start.pending_user_artifact_ids).toEqual(["art-1"]);
  });

  it("errors the turn when the staged retry upload also fails", async () => {
    const { service } = serviceWith({
      warm: [
        new Response(JSON.stringify({ task_id: "task-w", run_id: "run-w" }), {
          status: 200,
        }),
      ],
      command: [new Response("{}", { status: 200 })],
      prepare: [
        new Response("nope", { status: 500 }),
        new Response("nope", { status: 500 }),
      ],
      createTask: [taskResponse("task-1", null)],
    });
    await service.warm();
    const events = await collect(service, QUESTION, undefined, [SHOT]);
    expect(events.at(-1)).toMatchObject({ type: "error" });
  });

  it("attaches run artifacts to a follow-up user_message", async () => {
    const followUpTurn = [
      `data: ${promptEcho("and yesterday?")}\n\ndata: ${TURN_COMPLETE}\n\n`,
    ];
    const { service, fetchMock } = serviceWith({
      createTask: [taskResponse()],
      command: [new Response("{}", { status: 200 })],
      prepare: [preparedResponse(["art-2"])],
      finalize: [preparedResponse(["art-2"])],
      stream: [sseResponse(SIMPLE_TURN), sseResponse(followUpTurn)],
    });
    const first = await collect(service);
    await collect(service, "and yesterday?", conversationIdOf(first), [SHOT]);
    expect(callsTo(fetchMock, "/prepare_upload/")[0][1]).toContain(
      "/tasks/task-1/runs/run-1/artifacts/",
    );
    const command = JSON.parse(
      callsTo(fetchMock, "/command/")[0][2].body as string,
    );
    expect(command.params).toEqual({
      content: "and yesterday?",
      artifact_ids: ["art-2"],
    });
  });

  it("falls back to a fresh run when the live run rejects a follow-up", async () => {
    const followUpTurn = [
      `data: ${promptEcho("and yesterday?")}\n\ndata: ${TURN_COMPLETE}\n\n`,
    ];
    const { service, fetchMock } = serviceWith({
      createTask: [taskResponse()],
      command: [new Response("no active sandbox", { status: 400 })],
      createRun: [
        new Response(JSON.stringify({ id: "run-2" }), { status: 200 }),
      ],
      startRun: [new Response("{}", { status: 200 })],
      stream: [sseResponse(SIMPLE_TURN), sseResponse(followUpTurn)],
    });
    const first = await collect(service);
    const events = await collect(
      service,
      "and yesterday?",
      conversationIdOf(first),
    );
    expect(events.at(-1)).toEqual({ type: "done" });
    // The successor run is created on the same task and streamed from scratch.
    expect(callsTo(fetchMock, "/runs/")[0][1]).toContain("/tasks/task-1/");
    expect(callsTo(fetchMock, "/stream/")[1][1]).toContain("/runs/run-2/");
  });

  it("splits text around tool activity into segments and surfaces tool labels", async () => {
    const stream = sseResponse([
      `data: ${USER_ECHO}\n\n`,
      `data: ${agentText("Checking.")}\n\n`,
      `data: ${sessionUpdate({ sessionUpdate: "tool_call", title: "execute-sql" })}\n\n`,
      `data: ${agentText("1,204 signups this week.")}\n\n`,
      `data: ${TURN_COMPLETE}\n\n`,
    ]);
    const { service } = serviceWith({
      createTask: [taskResponse()],
      stream: [stream],
    });
    const events = await collect(service);
    expect(events).toContainEqual({
      type: "reasoning",
      content: "Running execute-sql…",
    });
    // The first segment completes when tool activity starts a second one.
    expect(events).toContainEqual({
      type: "text",
      id: "turn-1",
      content: "Checking.",
      complete: true,
    });
    expect(events).toContainEqual({
      type: "text",
      id: "turn-1.2",
      content: "1,204 signups this week.",
      complete: true,
    });
  });

  it("boot progress surfaces as a status label before the turn starts", async () => {
    const stream = sseResponse([
      `data: ${notification("_posthog/progress", { label: "Setting up sandbox", status: "in_progress", step: "sandbox" })}\n\n`,
      `data: ${USER_ECHO}\n\ndata: ${TURN_COMPLETE}\n\n`,
    ]);
    const { service } = serviceWith({
      createTask: [taskResponse()],
      stream: [stream],
    });
    const events = await collect(service);
    expect(events).toContainEqual({
      type: "reasoning",
      content: "Setting up sandbox",
    });
  });

  it("shows the latest thought line as the reasoning label", async () => {
    const stream = sseResponse([
      `data: ${USER_ECHO}\n\n`,
      `data: ${sessionUpdate({ sessionUpdate: "agent_thought_chunk", content: { type: "text", text: "Looking at signups\nby day" } })}\n\n`,
      `data: ${TURN_COMPLETE}\n\n`,
    ]);
    const { service } = serviceWith({
      createTask: [taskResponse()],
      stream: [stream],
    });
    const events = await collect(service);
    expect(events).toContainEqual({ type: "reasoning", content: "by day" });
  });

  it("reconnects from the cursor when the stream connection errors mid-read", async () => {
    const encoder = new TextEncoder();
    // Pull-based: erroring a stream discards queued chunks, so the frame must
    // deliver on the first read and the error on the second.
    let pulls = 0;
    const broken = new Response(
      new ReadableStream<Uint8Array>({
        pull(streamController) {
          pulls += 1;
          if (pulls === 1) {
            streamController.enqueue(
              encoder.encode(`id: 3-0\ndata: ${USER_ECHO}\n\n`),
            );
            return;
          }
          streamController.error(
            new TypeError("net::ERR_HTTP2_PROTOCOL_ERROR"),
          );
        },
      }),
      { status: 200 },
    );
    const second = sseResponse([
      `id: 4-0\ndata: ${agentText("Recovered.")}\n\nid: 5-0\ndata: ${TURN_COMPLETE}\n\n`,
    ]);
    const { service, fetchMock } = serviceWith({
      createTask: [taskResponse()],
      stream: [broken, second],
    });
    const events = await collect(service);
    expect(events).toContainEqual({
      type: "text",
      id: "turn-1",
      content: "Recovered.",
      complete: true,
    });
    expect(events.some((event) => event.type === "error")).toBe(false);
    const streamCalls = fetchMock.mock.calls.filter((call) =>
      String(call[1]).includes("/stream/"),
    );
    expect(streamCalls[1][2].headers["Last-Event-ID"]).toBe("3-0");
  });

  it("retries a stream connection that fails to open, then errors past the budget", async () => {
    const { service } = serviceWith({
      createTask: [taskResponse()],
      stream: [
        new Response("bad gateway", { status: 502 }),
        sseResponse([`data: ${USER_ECHO}\n\ndata: ${TURN_COMPLETE}\n\n`]),
      ],
    });
    const events = await collect(service);
    expect(events.at(-1)).toEqual({ type: "done" });
    expect(events.some((event) => event.type === "error")).toBe(false);
  });

  it("resumes across a stream rotation with the last event id", async () => {
    const first = sseResponse([
      `id: 7-0\ndata: ${USER_ECHO}\n\nevent: end\ndata: {"type":"rotated"}\n\n`,
    ]);
    const second = sseResponse([
      `id: 8-0\ndata: ${agentText("Done.")}\n\nid: 9-0\ndata: ${TURN_COMPLETE}\n\n`,
    ]);
    const { service, fetchMock } = serviceWith({
      createTask: [taskResponse()],
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

  it("takes only its own turn when the boot prompts the task description first", async () => {
    // The workflow prompts the task description at boot; prompt queueing logs
    // our prompt before that turn completes. The panel must skip the first
    // turn's output and completion, and take the second turn's.
    const stream = sseResponse([
      `data: ${promptEcho(QUESTION)}\n\n`,
      `data: ${USER_ECHO}\n\n`,
      `data: ${agentText("Description-turn answer.")}\n\n`,
      `data: ${TURN_COMPLETE}\n\n`,
      `data: ${agentText("Steered answer.")}\n\ndata: ${TURN_COMPLETE}\n\n`,
    ]);
    const { service } = serviceWith({
      createTask: [taskResponse()],
      stream: [stream],
    });
    const events = await collect(service);
    const texts = events.filter((event) => event.type === "text");
    expect(texts).toEqual([
      {
        type: "text",
        id: "turn-1",
        content: "Steered answer.",
        complete: false,
      },
      {
        type: "text",
        id: "turn-1",
        content: "Steered answer.",
        complete: true,
      },
    ]);
    expect(events.at(-1)).toEqual({ type: "done" });
  });

  it("ends the turn when the run reaches a terminal status", async () => {
    const stream = sseResponse([
      `data: ${USER_ECHO}\n\ndata: ${agentText("Partial answer.")}\n\n`,
      `data: ${JSON.stringify({ type: "task_run_state", status: "completed" })}\n\n`,
    ]);
    const { service } = serviceWith({
      createTask: [taskResponse()],
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
      createTask: [taskResponse()],
      stream: [stream],
    });
    const events = await collect(service);
    expect(events.at(-1)).toEqual({
      type: "error",
      message: "PostHog AI hit an error. Try asking again.",
      detail: "sandbox died",
    });
  });

  it("maps task creation failures: usage limits, access, and everything else", async () => {
    const cases: [number, string][] = [
      [402, "Your organization is out of PostHog task credits."],
      [429, "Your organization is out of PostHog task credits."],
      [403, "Your account can't run PostHog tasks in this project."],
      [503, "PostHog AI is unavailable right now (503)."],
    ];
    for (const [status, message] of cases) {
      const { service } = serviceWith({
        createTask: [new Response("nope", { status })],
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

  it("warm posts a repo-less warm request and swallows every outcome", async () => {
    const { service, fetchMock } = serviceWith({
      // Flag off / pool full: the endpoint returns an empty 200 body.
      warm: [new Response("", { status: 200 })],
    });
    await expect(service.warm()).resolves.toBeUndefined();
    const body = JSON.parse(
      callsTo(fetchMock, "/tasks/warm/")[0][2].body as string,
    );
    expect(body).toEqual({
      repository: null,
      repositories: [],
      github_integration: null,
      branch: null,
      runtime_adapter: null,
      model: null,
      reasoning_effort: null,
    });

    const failing = serviceWith({
      warm: [new Response("boom", { status: 500 })],
    });
    await expect(failing.service.warm()).resolves.toBeUndefined();
  });

  it("switches a warmed run to auto mode before activating it", async () => {
    const { service, fetchMock } = serviceWith({
      warm: [
        new Response(JSON.stringify({ task_id: "task-w", run_id: "run-w" }), {
          status: 200,
        }),
      ],
      command: [new Response("{}", { status: 200 })],
      createTask: [taskResponse("task-w", "run-w")],
      stream: [sseResponse(SIMPLE_TURN)],
    });
    await service.warm();
    await collect(service);
    const commandCalls = callsTo(fetchMock, "/command/");
    expect(commandCalls).toHaveLength(1);
    expect(commandCalls[0][1]).toContain("/runs/run-w/");
    expect(JSON.parse(commandCalls[0][2].body as string)).toMatchObject({
      method: "set_config_option",
      params: { configId: "mode", value: "auto" },
    });
    // The mode switch lands before the message-delivering create call.
    const commandIndex = fetchMock.mock.calls.findIndex((call) =>
      String(call[1]).endsWith("/command/"),
    );
    const createIndex = fetchMock.mock.calls.findIndex((call) =>
      String(call[1]).endsWith("/tasks/"),
    );
    expect(commandIndex).toBeLessThan(createIndex);
  });

  it("goes cold instead of reusing a warm run whose auto-mode switch failed", async () => {
    const { service, fetchMock } = serviceWith({
      warm: [
        new Response(JSON.stringify({ task_id: "task-w", run_id: "run-w" }), {
          status: 200,
        }),
      ],
      // The set_config_option command fails (e.g. the run is still booting).
      command: [new Response("boot", { status: 400 })],
      createTask: [taskResponse("task-1", null)],
      createRun: [
        new Response(JSON.stringify({ id: "run-9" }), { status: 200 }),
      ],
      startRun: [new Response("{}", { status: 200 })],
      stream: [sseResponse(SIMPLE_TURN)],
    });
    await service.warm();
    const events = await collect(service);
    expect(events.at(-1)).toEqual({ type: "done" });
    // No `branch` key: a warm run left in default mode would park the
    // question on an approval the panel cannot answer.
    const create = JSON.parse(
      callsTo(fetchMock, "/tasks/")[0][2].body as string,
    );
    expect("branch" in create).toBe(false);
    // The cold run sets auto mode server-side in its create body.
    const run = JSON.parse(callsTo(fetchMock, "/runs/")[0][2].body as string);
    expect(run.initial_permission_mode).toBe("auto");
  });

  it("exposes the thread's task id for open-in-app, cleared on reset", async () => {
    const { service } = serviceWith({
      createTask: [taskResponse()],
      stream: [sseResponse(SIMPLE_TURN)],
    });
    expect(service.currentTaskId).toBeNull();
    await collect(service);
    expect(service.currentTaskId).toBe("task-1");
    service.reset();
    expect(service.currentTaskId).toBeNull();
  });

  it("applies run defaults to warm and task creation", async () => {
    const { service, fetchMock } = serviceWith(
      {
        warm: [new Response("", { status: 200 })],
        createTask: [taskResponse()],
        stream: [sseResponse(SIMPLE_TURN)],
      },
      () => ({
        channelId: "chan-7",
        repositories: ["posthog/posthog"],
        githubIntegrationId: 42,
        adapter: "codex",
        model: "gpt-5.5",
        reasoningEffort: "high",
      }),
    );
    await service.warm();
    await collect(service);

    const warmBody = JSON.parse(
      callsTo(fetchMock, "/tasks/warm/")[0][2].body as string,
    );
    expect(warmBody).toMatchObject({
      repository: "posthog/posthog",
      repositories: ["posthog/posthog"],
      github_integration: 42,
      runtime_adapter: "codex",
      model: "gpt-5.5",
      reasoning_effort: "high",
    });
    const createBody = JSON.parse(
      callsTo(fetchMock, "/tasks/")[0][2].body as string,
    );
    expect(createBody).toMatchObject({
      channel: "chan-7",
      repositories: ["posthog/posthog"],
      github_integration: 42,
      runtime_adapter: "codex",
      model: "gpt-5.5",
      reasoning_effort: "high",
    });
  });

  it("a space default without repos leaves repositories to the space", async () => {
    const { service, fetchMock } = serviceWith(
      {
        createTask: [taskResponse()],
        stream: [sseResponse(SIMPLE_TURN)],
      },
      () => ({
        channelId: "chan-7",
        repositories: [],
        githubIntegrationId: null,
        adapter: null,
        model: null,
        reasoningEffort: null,
      }),
    );
    await collect(service);
    const createBody = JSON.parse(
      callsTo(fetchMock, "/tasks/")[0][2].body as string,
    );
    expect(createBody.channel).toBe("chan-7");
    expect(createBody).not.toHaveProperty("repositories");
  });

  it("reset drops the session so the next ask creates a new task", async () => {
    const { service, fetchMock } = serviceWith({
      createTask: [taskResponse(), taskResponse("task-2", "run-2")],
      stream: [sseResponse(SIMPLE_TURN), sseResponse(SIMPLE_TURN)],
    });
    await collect(service);
    service.reset();
    await collect(service);
    const creates = callsTo(fetchMock, "/tasks/");
    expect(creates).toHaveLength(2);
    // A fresh thread carries the steering block again.
    const secondBody = JSON.parse(creates[1][2].body as string);
    expect(secondBody.pending_user_message).toContain(
      "<posthog_trusted_context>",
    );
  });
});

describe("translateFrame", () => {
  it.each([
    [
      "agent text chunk",
      agentText("hi"),
      { kind: "agent-text", text: "hi", final: false },
    ],
    [
      "agent message snapshot",
      agentMessage("hi"),
      { kind: "agent-text", text: "hi", final: true },
    ],
    ["prompt echo", promptEcho("hello"), { kind: "prompt", text: "hello" }],
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
    [
      "user message chunk",
      sessionUpdate({
        sessionUpdate: "user_message_chunk",
        content: { type: "text", text: "hi" },
      }),
      { kind: "ignore", detail: "user_message_chunk" },
    ],
    // Permission waits are status signals so repeats replace the label
    // instead of accreting into the thought buffer.
    [
      "permission request",
      JSON.stringify({ type: "permission_request", requestId: "r1" }),
      { kind: "status", text: "Waiting for a tool approval…" },
    ],
    [
      "permission request over the session",
      notification("session/request_permission", { toolCallId: "t1" }),
      { kind: "status", text: "Waiting for a tool approval…" },
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
