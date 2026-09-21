import { afterEach, describe, expect, it } from "vitest";
import { Logger } from "../utils/logger";
import {
  McpRelayServer,
  RELAY_PAYLOAD_TOO_LARGE_CODE,
  RELAY_TIMEOUT_CODE,
} from "./mcp-relay-server";

const logger = new Logger({ debug: false, prefix: "[test]" });

interface Harness {
  relay: McpRelayServer;
  events: Record<string, unknown>[];
  post: (
    server: string,
    body: unknown,
    headers?: Record<string, string>,
  ) => Promise<Response>;
}

let active: McpRelayServer | null = null;

async function startRelay(options?: {
  servers?: string[];
  hasReachableClient?: () => boolean;
  requestTimeoutMs?: number;
  maxRequestBytes?: number;
}): Promise<Harness> {
  const events: Record<string, unknown>[] = [];
  const relay = new McpRelayServer({
    servers: options?.servers ?? ["slack"],
    emitEvent: (event) => events.push(event),
    hasReachableClient: options?.hasReachableClient ?? (() => true),
    logger,
    requestTimeoutMs: options?.requestTimeoutMs ?? 200,
    maxRequestBytes: options?.maxRequestBytes,
  });
  await relay.start();
  active = relay;

  const entries = relay.mcpServers;
  const byName = new Map(entries.map((entry) => [entry.name, entry]));
  const post = (
    server: string,
    body: unknown,
    headers?: Record<string, string>,
  ) => {
    const entry = byName.get(server);
    const url =
      entry?.url ??
      `${entries[0].url.split("/relay/")[0]}/relay/${encodeURIComponent(server)}`;
    const auth = entry?.headers[0] ?? entries[0].headers[0];
    return fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        [auth.name]: auth.value,
        ...headers,
      },
      body: typeof body === "string" ? body : JSON.stringify(body),
    });
  };
  return { relay, events, post };
}

afterEach(async () => {
  await active?.stop();
  active = null;
});

describe("McpRelayServer", () => {
  it("registers one loopback http entry per designated server", async () => {
    const { relay } = await startRelay({ servers: ["slack", "grafana"] });
    const entries = relay.mcpServers;
    expect(entries.map((e) => e.name).sort()).toEqual(["grafana", "slack"]);
    for (const entry of entries) {
      expect(entry.type).toBe("http");
      expect(entry.url).toMatch(/^http:\/\/127\.0\.0\.1:\d+\/relay\//);
      expect(entry.headers[0].name).toBe("Authorization");
    }
  });

  it("relays a request and returns the mcp_response payload verbatim", async () => {
    const { relay, events, post } = await startRelay();
    const responsePromise = post("slack", {
      jsonrpc: "2.0",
      id: 7,
      method: "tools/list",
    });

    await expect.poll(() => events.length).toBe(1);
    const event = events[0] as {
      requestId: string;
      server: string;
      type: string;
      expiresAt: string;
    };
    expect(event.type).toBe("mcp_request");
    expect(event.server).toBe("slack");
    expect(event.expiresAt).toMatch(/^\d{4}-/);

    const relayed = { jsonrpc: "2.0", id: 7, result: { tools: [] } };
    expect(
      relay.resolveResponse({
        requestId: event.requestId,
        server: "slack",
        payload: relayed,
      }),
    ).toBe(true);

    const response = await responsePromise;
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(relayed);
  });

  it("answers a JSON-RPC timeout error when the desktop never replies", async () => {
    const { post } = await startRelay({ requestTimeoutMs: 30 });
    const response = await post("slack", {
      jsonrpc: "2.0",
      id: 1,
      method: "x",
    });
    const body = (await response.json()) as { error: { code: number } };
    expect(body.error.code).toBe(RELAY_TIMEOUT_CODE);
  });

  it("drops late responses after the timeout fired", async () => {
    const { relay, events, post } = await startRelay({ requestTimeoutMs: 30 });
    await post("slack", { jsonrpc: "2.0", id: 1, method: "x" });
    const event = events[0] as { requestId: string };
    expect(
      relay.resolveResponse({
        requestId: event.requestId,
        server: "slack",
        payload: { jsonrpc: "2.0", id: 1, result: {} },
      }),
    ).toBe(false);
  });

  it("rejects responses that name the wrong server", async () => {
    const { relay, events, post } = await startRelay({
      servers: ["slack", "grafana"],
      requestTimeoutMs: 500,
    });
    const responsePromise = post("slack", {
      jsonrpc: "2.0",
      id: 1,
      method: "x",
    });
    await expect.poll(() => events.length).toBe(1);
    const event = events[0] as { requestId: string };
    expect(
      relay.resolveResponse({
        requestId: event.requestId,
        server: "grafana",
        payload: { jsonrpc: "2.0", id: 1, result: {} },
      }),
    ).toBe(false);
    expect(
      relay.resolveResponse({
        requestId: event.requestId,
        server: "slack",
        payload: { jsonrpc: "2.0", id: 1, result: {} },
      }),
    ).toBe(true);
    await responsePromise;
  });

  it("rejects oversized payloads without emitting an event", async () => {
    const { events, post } = await startRelay({ maxRequestBytes: 64 });
    const response = await post("slack", {
      jsonrpc: "2.0",
      id: 1,
      method: "x",
      params: { blob: "y".repeat(200) },
    });
    const body = (await response.json()) as { error: { code: number } };
    expect(body.error.code).toBe(RELAY_PAYLOAD_TOO_LARGE_CODE);
    expect(events).toHaveLength(0);
  });

  it("relays notifications fire-and-forget with a 202", async () => {
    const { events, post } = await startRelay();
    const response = await post("slack", {
      jsonrpc: "2.0",
      method: "notifications/initialized",
    });
    expect(response.status).toBe(202);
    await expect.poll(() => events.length).toBe(1);
  });

  it("503s only after a client has been reachable and then went away", async () => {
    let reachable = true;
    const { events, post } = await startRelay({
      hasReachableClient: () => reachable,
      requestTimeoutMs: 30,
    });
    // First request establishes reachability (times out here since no
    // response is delivered, but that's fine — it marks the endpoint live).
    await post("slack", { jsonrpc: "2.0", id: 1, method: "x" });
    expect(events).toHaveLength(1);

    reachable = false;
    const response = await post("slack", {
      jsonrpc: "2.0",
      id: 2,
      method: "x",
    });
    expect(response.status).toBe(503);
    expect(events).toHaveLength(1);
  });

  it("buffers the startup request instead of 503ing before any client attaches", async () => {
    let reachable = false;
    const { relay, events, post } = await startRelay({
      hasReachableClient: () => reachable,
      requestTimeoutMs: 2_000,
    });
    // A relayed request (tools/list) fires before the event relay attaches.
    const responsePromise = post("slack", {
      jsonrpc: "2.0",
      id: 1,
      method: "tools/list",
    });
    await expect.poll(() => events.length).toBe(1);
    const event = events[0] as { requestId: string };

    // Client attaches ~now and answers the buffered request.
    reachable = true;
    const relayed = { jsonrpc: "2.0", id: 1, result: {} };
    relay.resolveResponse({
      requestId: event.requestId,
      server: "slack",
      payload: relayed,
    });
    const response = await responsePromise;
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(relayed);
  });

  it("answers 401 without the per-run bearer and 404 for undesignated names", async () => {
    const { relay, post } = await startRelay();
    const entry = relay.mcpServers[0];
    const unauthorized = await fetch(entry.url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "x" }),
    });
    expect(unauthorized.status).toBe(401);

    const unknown = await post("not-designated", {
      jsonrpc: "2.0",
      id: 1,
      method: "x",
    });
    expect(unknown.status).toBe(404);
  });

  it("drains pending requests with an error on stop", async () => {
    const { relay, events, post } = await startRelay({
      requestTimeoutMs: 5_000,
    });
    const responsePromise = post("slack", {
      jsonrpc: "2.0",
      id: 1,
      method: "x",
    });
    await expect.poll(() => events.length).toBe(1);
    await relay.stop();
    const body = (await (await responsePromise).json()) as {
      error: { code: number; message: string };
    };
    expect(body.error.code).toBe(RELAY_TIMEOUT_CODE);
    expect(body.error.message).toMatch(/shutting down/i);
  });

  it("returns invalid JSON as a parse error", async () => {
    const { post } = await startRelay();
    const response = await post("slack", "{not json");
    const body = (await response.json()) as { error: { code: number } };
    expect(body.error.code).toBe(-32700);
  });
});
