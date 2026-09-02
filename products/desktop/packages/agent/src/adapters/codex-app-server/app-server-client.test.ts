import { describe, expect, it, vi } from "vitest";
import { Logger } from "../../utils/logger";
import {
  createBidirectionalStreams,
  type StreamPair,
} from "../../utils/streams";
import { AppServerClient, AppServerRequestError } from "./app-server-client";

interface RpcMessage {
  id?: number | string;
  method?: string;
  params?: unknown;
  result?: unknown;
  error?: { code: number; message: string };
}

/** Drives the "server" end of a {@link StreamPair}: reads client JSON-RPC and writes framed replies back. */
function makeFakeServer(transport: StreamPair) {
  const writer = transport.writable.getWriter();
  const reader = transport.readable.getReader();
  const encoder = new TextEncoder();
  const decoder = new TextDecoder();
  let buffer = "";

  return {
    async readMessage(): Promise<RpcMessage> {
      for (let guard = 0; guard < 10_000; guard++) {
        const newlineIndex = buffer.indexOf("\n");
        if (newlineIndex !== -1) {
          const line = buffer.slice(0, newlineIndex).trim();
          buffer = buffer.slice(newlineIndex + 1);
          if (line) return JSON.parse(line) as RpcMessage;
          continue;
        }
        const { value, done } = await reader.read();
        if (done) throw new Error("server stream closed");
        buffer += decoder.decode(value, { stream: true });
      }
      throw new Error("no message read");
    },
    async send(message: RpcMessage): Promise<void> {
      await writer.write(encoder.encode(`${JSON.stringify(message)}\n`));
    },
  };
}

const silentLogger = new Logger({ debug: false });

describe("AppServerClient", () => {
  it("resolves a request when the server returns a matching response", async () => {
    const streams = createBidirectionalStreams();
    const client = new AppServerClient(streams.client, {
      logger: silentLogger,
    });
    const server = makeFakeServer(streams.agent);

    const pending = client.request("initialize", {
      clientInfo: { name: "posthog-code" },
    });

    const request = await server.readMessage();
    expect(request.method).toBe("initialize");
    expect(typeof request.id).toBe("number");
    expect(request.params).toEqual({ clientInfo: { name: "posthog-code" } });

    await server.send({
      id: request.id as number,
      result: { userAgent: "codex" },
    });

    await expect(pending).resolves.toEqual({ userAgent: "codex" });
    await client.close();
  });

  it("rejects a request when the server returns an error", async () => {
    const streams = createBidirectionalStreams();
    const client = new AppServerClient(streams.client, {
      logger: silentLogger,
    });
    const server = makeFakeServer(streams.agent);

    const pending = client.request("turn/start", {});
    const request = await server.readMessage();
    await server.send({
      id: request.id as number,
      error: { code: -32001, message: "Server overloaded; retry later." },
    });

    const error = await pending.catch((requestError: unknown) => requestError);
    expect(error).toBeInstanceOf(AppServerRequestError);
    expect(error).toMatchObject({
      code: -32001,
      message: "Server overloaded; retry later.",
    });
    await client.close();
  });

  it("dispatches server notifications to the handler in order", async () => {
    const streams = createBidirectionalStreams();
    const received: string[] = [];
    const client = new AppServerClient(streams.client, {
      logger: silentLogger,
      onNotification: (method, params) => {
        if (method === "item/agentMessage/delta") {
          received.push((params as { delta: string }).delta);
        }
      },
    });
    const server = makeFakeServer(streams.agent);

    await server.send({
      method: "item/agentMessage/delta",
      params: { delta: "Hel" },
    });
    await server.send({
      method: "item/agentMessage/delta",
      params: { delta: "lo" },
    });

    await vi.waitFor(() => expect(received.length).toBe(2));
    expect(received.join("")).toBe("Hello");
    await client.close();
  });

  it("answers server-initiated requests via onRequest", async () => {
    const streams = createBidirectionalStreams();
    const client = new AppServerClient(streams.client, {
      logger: silentLogger,
      onRequest: async (method) => ({
        decision: method === "applyPatchApproval" ? "approved" : "denied",
      }),
    });
    const server = makeFakeServer(streams.agent);

    await server.send({
      id: 99,
      method: "applyPatchApproval",
      params: {},
    });

    const response = await server.readMessage();
    expect(response.id).toBe(99);
    expect(response.result).toEqual({ decision: "approved" });
    await client.close();
  });

  it("answers a server request with a STRING id (RequestId is string|number)", async () => {
    const streams = createBidirectionalStreams();
    const onRequest = vi.fn(async () => ({ decision: "approved" }));
    const client = new AppServerClient(streams.client, {
      logger: silentLogger,
      onRequest,
    });
    const server = makeFakeServer(streams.agent);

    await server.send({
      id: "req-abc",
      method: "item/commandExecution/requestApproval",
      params: {},
    });

    const response = await server.readMessage();
    expect(onRequest).toHaveBeenCalledTimes(1);
    expect(response.id).toBe("req-abc");
    expect(response.result).toEqual({ decision: "approved" });
    await client.close();
  });

  it("rejects in-flight requests when closed", async () => {
    const streams = createBidirectionalStreams();
    const client = new AppServerClient(streams.client, {
      logger: silentLogger,
    });

    const pending = client.request("thread/start", {});
    await client.close();

    await expect(pending).rejects.toThrow(/closed/i);
  });

  it("rejects new requests immediately once closed instead of registering them", async () => {
    const streams = createBidirectionalStreams();
    const client = new AppServerClient(streams.client, {
      logger: silentLogger,
    });

    await client.close();

    await expect(client.request("turn/interrupt", {})).rejects.toThrow(
      /closed/i,
    );
    expect(() => client.notify("thread/archive", {})).not.toThrow();
  });

  it("rejects new requests after the stream ends without close (process exit)", async () => {
    const streams = createBidirectionalStreams();
    const onClose = vi.fn();
    const client = new AppServerClient(streams.client, {
      logger: silentLogger,
      onClose,
    });

    await streams.agent.writable.getWriter().close();
    await vi.waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));

    await expect(client.request("turn/interrupt", {})).rejects.toThrow(
      /closed/i,
    );
  });
});
