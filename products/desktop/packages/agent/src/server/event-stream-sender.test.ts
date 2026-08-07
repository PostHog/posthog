import { afterEach, describe, expect, it, vi } from "vitest";
import { Logger } from "../utils/logger";
import { TaskRunEventStreamSender } from "./event-stream-sender";

const STREAM_COMPLETE_CONTROL_TYPE = "_posthog/stream_complete";

async function readRequestBody(init?: RequestInit): Promise<string> {
  const body = init?.body;
  if (!body) {
    return "";
  }
  if (typeof body === "string") {
    return body;
  }
  if (body instanceof Uint8Array) {
    return new TextDecoder().decode(body);
  }
  if (body instanceof ReadableStream) {
    const reader = body.getReader();
    const chunks: Uint8Array[] = [];
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      chunks.push(value);
    }
    const length = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
    const bytes = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.length;
    }
    return new TextDecoder().decode(bytes);
  }
  return String(body);
}

function parseLines(body: string): Record<string, unknown>[] {
  const trimmed = body.trim();
  if (!trimmed) {
    return [];
  }
  return trimmed.split("\n").map((line) => JSON.parse(line));
}

function eventSequences(body: string): number[] {
  return parseLines(body)
    .map((line) => line.seq)
    .filter((seq): seq is number => typeof seq === "number");
}

function completionSequences(body: string): number[] {
  return parseLines(body)
    .filter((line) => line.type === STREAM_COMPLETE_CONTROL_TYPE)
    .map((line) => line.final_seq)
    .filter((seq): seq is number => typeof seq === "number");
}

function responseForBody(body: string, lastAcceptedSeq = 0): Response {
  const sequences = eventSequences(body);
  const acceptedSeq = sequences.at(-1) ?? lastAcceptedSeq;
  return new Response(JSON.stringify({ last_accepted_seq: acceptedSeq }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

type StreamingRequestInit = RequestInit & { duplex: "half" };

function createFetchStreamingUpload({
  url,
  headers,
  abortController,
}: {
  url: string;
  headers: Record<string, string>;
  abortController: AbortController;
}) {
  const bodyStream = new TransformStream<Uint8Array, Uint8Array>();
  const writer = bodyStream.writable.getWriter();
  const requestInit: StreamingRequestInit = {
    method: "POST",
    headers,
    body: bodyStream.readable as BodyInit,
    signal: abortController.signal,
    duplex: "half",
  };

  return {
    write(chunk: Uint8Array): Promise<void> {
      return writer.write(chunk);
    },
    close(): Promise<void> {
      return writer.close();
    },
    async abort(): Promise<void> {
      abortController.abort();
      try {
        await writer.abort();
      } catch {
        // The fetch mock may have already closed the body reader.
      }
    },
    responsePromise: fetch(url, requestInit),
  };
}

function createSender(
  options: Partial<
    ConstructorParameters<typeof TaskRunEventStreamSender>[0]
  > = {},
): TaskRunEventStreamSender {
  return new TaskRunEventStreamSender({
    apiUrl: "http://localhost:8000/",
    projectId: 1,
    taskId: "task-1",
    runId: "run-1",
    token: "ingest-token",
    logger: new Logger({ debug: false }),
    createStreamingUpload: createFetchStreamingUpload,
    ...options,
  });
}

describe("TaskRunEventStreamSender", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("streams ordered NDJSON events with the run-scoped token", async () => {
    const requestBodies: string[] = [];
    const fetchMock = vi.fn(
      async (_url: string | URL | Request, init?: RequestInit) => {
        const body = await readRequestBody(init);
        requestBodies.push(body);
        return responseForBody(body);
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    const sender = createSender();

    sender.enqueue({ type: "notification", notification: { method: "first" } });
    sender.enqueue({
      type: "notification",
      notification: { method: "second" },
    });
    await sender.stop();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1][0]).toBe(
      "http://localhost:8000/api/projects/1/tasks/task-1/runs/run-1/event_stream/",
    );
    expect(fetchMock.mock.calls[1][1]?.headers).toEqual({
      Authorization: "Bearer ingest-token",
      "Content-Type": "application/x-ndjson",
    });
    expect(fetchMock.mock.calls[1][1]?.headers).not.toHaveProperty(
      "X-PostHog-Event-Stream-Complete",
    );

    expect(parseLines(requestBodies[1])).toEqual([
      {
        seq: 1,
        event: { type: "notification", notification: { method: "first" } },
      },
      {
        seq: 2,
        event: { type: "notification", notification: { method: "second" } },
      },
      { type: STREAM_COMPLETE_CONTROL_TYPE, final_seq: 2 },
    ]);
  });

  it("routes the ingest POST to the agent-proxy run-scoped path when eventIngestBaseUrl is set", async () => {
    const fetchMock = vi.fn(
      async (_url: string | URL | Request, init?: RequestInit) => {
        const body = await readRequestBody(init);
        return responseForBody(body);
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    const sender = createSender({
      eventIngestBaseUrl: "http://agent-proxy:8003/",
    });
    sender.enqueue({ type: "notification", notification: { method: "first" } });
    await sender.stop();

    expect(fetchMock).toHaveBeenCalled();
    const lastCall = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
    expect(lastCall[0]).toBe("http://agent-proxy:8003/v1/runs/run-1/ingest");
    expect(lastCall[0]).not.toContain("/api/projects/");
  });

  it("closes the ingest upload per drained batch on the proxy path by default", async () => {
    const requestBodies: string[] = [];
    let contentUploads = 0;
    const fetchMock = vi.fn(
      async (_url: string | URL | Request, init?: RequestInit) => {
        if (!init?.body || typeof init.body === "string") {
          return responseForBody(await readRequestBody(init));
        }

        // Resolves only once the sender closes the upload body.
        const body = await readRequestBody(init);
        contentUploads += 1;
        requestBodies.push(body);
        return responseForBody(body);
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    const sender = createSender({
      flushDelayMs: 0,
      eventIngestBaseUrl: "http://agent-proxy:8003/",
    });

    sender.enqueue({ type: "notification", notification: { method: "first" } });
    await vi.waitFor(() => expect(contentUploads).toBe(1));

    sender.enqueue({
      type: "notification",
      notification: { method: "second" },
    });
    await vi.waitFor(() => expect(contentUploads).toBe(2));

    await sender.stop();

    expect(eventSequences(requestBodies[0] ?? "")).toEqual([1]);
    expect(eventSequences(requestBodies[1] ?? "")).toEqual([2]);
  });

  it("holds one long-lived upload across batches when keepProxyStreamOpen is set", async () => {
    const requestBodies: string[] = [];
    let streamingRequests = 0;
    let contentUploads = 0;
    const fetchMock = vi.fn(
      async (_url: string | URL | Request, init?: RequestInit) => {
        if (!init?.body || typeof init.body === "string") {
          return responseForBody(await readRequestBody(init));
        }

        // Counted on open; resolves only once the sender closes the upload body.
        streamingRequests += 1;
        const body = await readRequestBody(init);
        contentUploads += 1;
        requestBodies.push(body);
        return responseForBody(body);
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    const sender = createSender({
      flushDelayMs: 0,
      eventIngestBaseUrl: "http://agent-proxy:8003/",
      keepProxyStreamOpen: true,
    });

    sender.enqueue({ type: "notification", notification: { method: "first" } });
    // First batch opens the upload and holds it open: nothing is delivered yet.
    await vi.waitFor(() => expect(streamingRequests).toBe(1));
    expect(contentUploads).toBe(0);

    // A second batch reuses the held-open upload instead of opening another.
    sender.enqueue({
      type: "notification",
      notification: { method: "second" },
    });
    await sender.stop();

    expect(streamingRequests).toBe(1);
    expect(contentUploads).toBe(1);
    const finalBody = requestBodies.at(-1) ?? "";
    expect(eventSequences(finalBody)).toEqual([1, 2]);
    expect(completionSequences(finalBody)).toEqual([2]);
  });

  it("aborts a stuck ingest response after closing the request body", async () => {
    let aborted = false;
    const fetchMock = vi.fn(
      async (_url: string | URL | Request, init?: RequestInit) => {
        if (!init?.body || typeof init.body === "string") {
          return new Response(JSON.stringify({ last_accepted_seq: 0 }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }

        void readRequestBody(init);
        return new Promise<Response>((_resolve, reject) => {
          init.signal?.addEventListener("abort", () => {
            aborted = true;
            reject(new DOMException("aborted", "AbortError"));
          });
        });
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    const sender = createSender({
      requestTimeoutMs: 1,
      retryDelayMs: 1,
      stopTimeoutMs: 1,
    });

    sender.enqueue({ type: "notification", notification: { method: "first" } });
    await sender.stop();

    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(aborted).toBe(true);
  });

  it("waits for the final ingest response before stop resolves", async () => {
    const ingestRequest: { resolve?: (response: Response) => void } = {};
    let stopped = false;
    const fetchMock = vi.fn(
      async (_url: string | URL | Request, init?: RequestInit) => {
        if (!init?.body || typeof init.body === "string") {
          return new Response(JSON.stringify({ last_accepted_seq: 0 }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }

        void readRequestBody(init);
        return new Promise<Response>((resolve) => {
          ingestRequest.resolve = resolve;
        });
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    const sender = createSender();

    sender.enqueue({ type: "notification", notification: { method: "first" } });
    const stopPromise = sender.stop().then(() => {
      stopped = true;
    });

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(stopped).toBe(false);

    const resolveIngest = ingestRequest.resolve;
    if (!resolveIngest) {
      throw new Error("expected ingest request to be in flight");
    }
    resolveIngest(
      new Response(JSON.stringify({ last_accepted_seq: 1 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await stopPromise;

    expect(stopped).toBe(true);
  });

  it("streams only a completion control line on shutdown without buffered events", async () => {
    const requestBodies: string[] = [];
    const fetchMock = vi.fn(
      async (_url: string | URL | Request, init?: RequestInit) => {
        const body = await readRequestBody(init);
        requestBodies.push(body);
        return responseForBody(body);
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    const sender = createSender();

    await sender.stop();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(requestBodies[0]).toBe("");
    expect(parseLines(requestBodies[1])).toEqual([
      { type: STREAM_COMPLETE_CONTROL_TYPE, final_seq: 0 },
    ]);
  });

  it.each([
    {
      name: "when the buffer is full",
      senderOptions: { maxBufferedEvents: 1 },
      events: [
        { type: "notification", notification: { method: "first" } },
        { type: "notification", notification: { method: "second" } },
      ],
      acceptedMethod: "first",
    },
    {
      name: "when an event is oversized",
      senderOptions: { maxEventBytes: 120 },
      events: [
        {
          type: "notification",
          notification: {
            method: "oversized",
            params: { message: "x".repeat(200) },
          },
        },
        { type: "notification", notification: { method: "small" } },
      ],
      acceptedMethod: "small",
    },
  ])(
    "drops events before assigning sequence $name",
    async ({ senderOptions, events, acceptedMethod }) => {
      const requestBodies: string[] = [];
      const fetchMock = vi.fn(
        async (_url: string | URL | Request, init?: RequestInit) => {
          const body = await readRequestBody(init);
          requestBodies.push(body);
          return responseForBody(body);
        },
      );
      vi.stubGlobal("fetch", fetchMock);

      const sender = createSender(senderOptions);

      for (const event of events) {
        sender.enqueue(event);
      }
      await sender.stop();

      expect(parseLines(requestBodies[1])).toEqual([
        {
          seq: 1,
          event: {
            type: "notification",
            notification: { method: acceptedMethod },
          },
        },
        { type: STREAM_COMPLETE_CONTROL_TYPE, final_seq: 1 },
      ]);
    },
  );

  it("accepts an event at the next sequence size boundary", async () => {
    const requestBodies: string[] = [];
    const fetchMock = vi.fn(
      async (_url: string | URL | Request, init?: RequestInit) => {
        const body = await readRequestBody(init);
        requestBodies.push(body);
        return responseForBody(body);
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    const event = {
      type: "notification",
      notification: { method: "boundary" },
    };
    const maxEventBytes = new TextEncoder().encode(
      JSON.stringify({ seq: 1, event }),
    ).length;

    const sender = createSender({ maxEventBytes });

    sender.enqueue(event);
    await sender.stop();

    expect(parseLines(requestBodies[1])).toEqual([
      {
        seq: 1,
        event: {
          type: "notification",
          notification: { method: "boundary" },
        },
      },
      { type: STREAM_COMPLETE_CONTROL_TYPE, final_seq: 1 },
    ]);
  });

  it("rolls capped streams on stop", async () => {
    const requestBodies: string[] = [];
    const fetchMock = vi.fn(
      async (_url: string | URL | Request, init?: RequestInit) => {
        const body = await readRequestBody(init);
        requestBodies.push(body);
        return responseForBody(body);
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    const sender = createSender({ maxStreamEvents: 1 });

    sender.enqueue({ type: "notification", notification: { method: "first" } });
    sender.enqueue({
      type: "notification",
      notification: { method: "second" },
    });
    await sender.stop();

    expect(requestBodies).toHaveLength(3);
    expect(eventSequences(requestBodies[1])).toEqual([1]);
    expect(completionSequences(requestBodies[1])).toEqual([]);
    expect(eventSequences(requestBodies[2])).toEqual([2]);
    expect(completionSequences(requestBodies[2])).toEqual([2]);
  });

  it("retries stop drain after a transient ingest failure", async () => {
    const requestBodies: string[] = [];
    const fetchMock = vi.fn(
      async (_url: string | URL | Request, init?: RequestInit) => {
        const body = await readRequestBody(init);
        if (!body) {
          return new Response(JSON.stringify({ last_accepted_seq: 0 }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }

        requestBodies.push(body);
        if (requestBodies.length === 1) {
          return new Response("temporary failure", { status: 503 });
        }

        return responseForBody(body);
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    const sender = createSender({
      retryDelayMs: 1,
      stopTimeoutMs: 100,
    });

    sender.enqueue({ type: "notification", notification: { method: "first" } });
    await sender.stop();

    expect(requestBodies.map(eventSequences)).toEqual([[1], [1]]);
    expect(completionSequences(requestBodies[1])).toEqual([1]);
  });

  it("retries when the active stream response rejects before shutdown", async () => {
    const requestBodies: string[] = [];
    let failedStream = false;
    const fetchMock = vi.fn(
      async (_url: string | URL | Request, init?: RequestInit) => {
        if (!init?.body || typeof init.body === "string") {
          return new Response(JSON.stringify({ last_accepted_seq: 0 }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }

        if (!failedStream) {
          failedStream = true;
          throw new TypeError("fetch failed");
        }

        const body = await readRequestBody(init);
        requestBodies.push(body);
        return responseForBody(body);
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    const sender = createSender({
      retryDelayMs: 1,
      stopTimeoutMs: 100,
    });

    sender.enqueue({ type: "notification", notification: { method: "first" } });
    await sender.stop();

    expect(requestBodies.map(eventSequences)).toEqual([[1]]);
    expect(completionSequences(requestBodies[0])).toEqual([1]);
  });

  it("stops retrying after the stop deadline", async () => {
    const requestBodies: string[] = [];
    const warnings: string[] = [];
    const fetchMock = vi.fn(
      async (_url: string | URL | Request, init?: RequestInit) => {
        const body = await readRequestBody(init);
        if (!body) {
          return new Response(JSON.stringify({ last_accepted_seq: 0 }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }

        requestBodies.push(body);
        return new Response("temporary failure", { status: 503 });
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    const sender = createSender({
      logger: new Logger({
        debug: false,
        onLog: (level, _scope, message) => {
          if (level === "warn") {
            warnings.push(message);
          }
        },
      }),
      retryDelayMs: 10_000,
      stopTimeoutMs: 0,
    });

    sender.enqueue({ type: "notification", notification: { method: "first" } });
    await sender.stop();

    expect(requestBodies).toHaveLength(1);
    expect(eventSequences(requestBodies[0])).toEqual([1]);
    expect(warnings).toContain(
      "Task run event ingest stop deadline reached before fully completing transport",
    );
  });

  it("continues after a payload error acknowledges a valid prefix", async () => {
    const requestBodies: string[] = [];
    const fetchMock = vi.fn(
      async (_url: string | URL | Request, init?: RequestInit) => {
        const body = await readRequestBody(init);
        if (!body) {
          return new Response(JSON.stringify({ last_accepted_seq: 0 }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        requestBodies.push(body);

        if (requestBodies.length === 1) {
          return new Response(
            JSON.stringify({
              error: "Too many events in request",
              last_accepted_seq: 1,
            }),
            {
              status: 413,
              headers: { "Content-Type": "application/json" },
            },
          );
        }

        return responseForBody(body);
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    const sender = createSender({
      retryDelayMs: 1,
      stopTimeoutMs: 100,
    });

    sender.enqueue({ type: "notification", notification: { method: "first" } });
    sender.enqueue({
      type: "notification",
      notification: { method: "second" },
    });
    await sender.stop();

    expect(requestBodies.map(eventSequences)).toEqual([[1, 2], [2]]);
    expect(completionSequences(requestBodies[1])).toEqual([2]);
  });

  it("starts after the server's last accepted sequence on restart", async () => {
    const requestBodies: string[] = [];
    const fetchMock = vi.fn(
      async (_url: string | URL | Request, init?: RequestInit) => {
        const body = await readRequestBody(init);
        if (!body) {
          return new Response(JSON.stringify({ last_accepted_seq: 42 }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        requestBodies.push(body);
        return responseForBody(body);
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    const sender = createSender();

    sender.enqueue({
      type: "notification",
      notification: { method: "after-restart" },
    });
    sender.enqueue({ type: "notification", notification: { method: "next" } });
    await sender.stop();

    expect(eventSequences(requestBodies[0])).toEqual([43, 44]);
    expect(completionSequences(requestBodies[0])).toEqual([44]);
  });

  it("rebases buffered events after a sequence gap response", async () => {
    const requestBodies: string[] = [];
    const fetchMock = vi.fn(
      async (_url: string | URL | Request, init?: RequestInit) => {
        const body = await readRequestBody(init);
        if (!body) {
          return new Response(JSON.stringify({ last_accepted_seq: 42 }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }

        requestBodies.push(body);
        if (requestBodies.length === 1) {
          return new Response(
            JSON.stringify({
              error: "Expected sequence 1, got 43",
              last_accepted_seq: 0,
            }),
            {
              status: 409,
              headers: { "Content-Type": "application/json" },
            },
          );
        }

        return responseForBody(body);
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    const sender = createSender({
      retryDelayMs: 1,
      stopTimeoutMs: 100,
    });

    sender.enqueue({
      type: "notification",
      notification: { method: "after-expiry" },
    });
    sender.enqueue({ type: "notification", notification: { method: "next" } });
    await sender.stop();

    expect(requestBodies.map(eventSequences)).toEqual([
      [43, 44],
      [1, 2],
    ]);
    expect(completionSequences(requestBodies[1])).toEqual([2]);
  });

  it("reconnects and replays only events after the server's accepted prefix", async () => {
    const requestBodies: string[] = [];
    let syncCount = 0;
    const fetchMock = vi.fn(
      async (_url: string | URL | Request, init?: RequestInit) => {
        const body = await readRequestBody(init);
        if (!body) {
          syncCount += 1;
          return new Response(
            JSON.stringify({ last_accepted_seq: syncCount === 1 ? 0 : 1 }),
            {
              status: 200,
              headers: { "Content-Type": "application/json" },
            },
          );
        }

        requestBodies.push(body);
        if (requestBodies.length === 1) {
          throw new Error("connection reset");
        }

        return responseForBody(body);
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    const sender = createSender({
      retryDelayMs: 1,
      stopTimeoutMs: 100,
    });

    sender.enqueue({ type: "notification", notification: { method: "first" } });
    sender.enqueue({
      type: "notification",
      notification: { method: "second" },
    });
    await sender.stop();

    expect(requestBodies.map(eventSequences)).toEqual([[1, 2], [2]]);
    expect(completionSequences(requestBodies[1])).toEqual([2]);
  });
});
