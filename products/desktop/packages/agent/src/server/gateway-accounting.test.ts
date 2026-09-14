import * as http from "node:http";
import { gzipSync } from "node:zlib";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PostHogAPIClient } from "../posthog-api";
import { GatewayAccountingProxy } from "./gateway-accounting";

const servers: http.Server[] = [];

async function listen(server: http.Server): Promise<string> {
  servers.push(server);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string")
    throw new Error("missing address");
  return `http://127.0.0.1:${address.port}`;
}

async function request(
  url: string,
  headers: http.OutgoingHttpHeaders,
  method = "GET",
): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    http
      .request(url, { headers, method }, (response) => {
        const chunks: Buffer[] = [];
        response.on("data", (chunk: Buffer) => chunks.push(chunk));
        response.on("end", () => resolve(Buffer.concat(chunks)));
      })
      .on("error", reject)
      .end();
  });
}

afterEach(async () => {
  await Promise.all(
    servers
      .splice(0)
      .map(
        (server) =>
          new Promise<void>((resolve) => server.close(() => resolve())),
      ),
  );
});

describe("GatewayAccountingProxy", () => {
  it("records intent before dispatch and forwards compressed bytes with the private bearer", async () => {
    const observed: { authorization?: string; beforeIntent?: boolean } = {};
    let intentRecorded = false;
    const upstream = await listen(
      http.createServer((request, response) => {
        observed.authorization = request.headers.authorization;
        observed.beforeIntent = intentRecorded;
        const body = gzipSync("compressed upstream body");
        response.writeHead(200, {
          "content-encoding": "gzip",
          "content-length": body.length,
          "x-request-id": "gateway-request",
        });
        response.end(body);
      }),
    );
    const gatewayUsage = vi.fn(
      async (
        _taskId: string,
        _runId: string,
        operation: { operation: string },
      ) => {
        if (operation.operation === "request") intentRecorded = true;
        return {
          settled: operation.operation === "settle",
          spend: {
            token_cost: null,
            compute_cost: null,
            token_status: "partial" as const,
            compute_status: "unavailable" as const,
            is_final: false,
          },
        };
      },
    );
    const proxy = new GatewayAccountingProxy({
      api: { gatewayUsage } as unknown as PostHogAPIClient,
      taskId: "task-example",
      runId: "run-example",
      upstreamUrl: upstream,
      upstreamBearer: "private-bearer",
      logger: { warn: vi.fn() } as never,
    });

    await proxy.start();
    const body = await request(
      `${proxy.baseUrl}/v1/messages`,
      { authorization: `Bearer ${proxy.bearer}` },
      "POST",
    );
    await proxy.stop();

    expect(body).toEqual(gzipSync("compressed upstream body"));
    expect(observed).toEqual({
      authorization: "Bearer private-bearer",
      beforeIntent: true,
    });
    expect(
      (
        gatewayUsage.mock.calls as unknown as Array<
          [string, string, { operation: string }]
        >
      ).map((call) => call[2].operation),
    ).toEqual(["start", "request", "request", "settle", "finish"]);
  });

  it("accepts the Anthropic x-api-key, removes hop-by-hop headers, and avoids a double v1 prefix", async () => {
    const observed: {
      authorization?: string;
      xApiKey?: string;
      nominated?: string;
      url?: string;
    } = {};
    const upstream = await listen(
      http.createServer((request, response) => {
        observed.authorization = request.headers.authorization;
        observed.xApiKey = request.headers["x-api-key"] as string | undefined;
        observed.nominated = request.headers["x-remove-me"] as
          | string
          | undefined;
        observed.url = request.url;
        response.end("ok");
      }),
    );
    const gatewayUsage = vi.fn(async () => ({
      settled: true,
      spend: {
        token_cost: null,
        compute_cost: null,
        token_status: "partial" as const,
        compute_status: "unavailable" as const,
        is_final: false,
      },
    }));
    const proxy = new GatewayAccountingProxy({
      api: { gatewayUsage } as unknown as PostHogAPIClient,
      taskId: "task-example",
      runId: "run-example",
      upstreamUrl: `${upstream}/v1`,
      upstreamBearer: "private-bearer",
      logger: { warn: vi.fn() } as never,
    });

    await proxy.start();
    await request(
      `${proxy.baseUrl}/v1/messages`,
      {
        "x-api-key": proxy.bearer,
        connection: "x-remove-me",
        "x-remove-me": "secret",
      },
      "POST",
    );
    await proxy.stop();

    expect(observed).toEqual({
      authorization: "Bearer private-bearer",
      xApiKey: undefined,
      nominated: undefined,
      url: "/v1/messages",
    });
  });

  it("retries an unsettled receipt after the response stream ends", async () => {
    const upstream = await listen(
      http.createServer((_request, response) => {
        response.writeHead(200, { "x-request-id": "gateway-request" });
        response.end("ok");
      }),
    );
    let settleCalls = 0;
    const gatewayUsage = vi.fn(
      async (_task: string, _run: string, operation: { operation: string }) => {
        if (operation.operation === "settle") settleCalls += 1;
        return {
          settled: operation.operation !== "settle" || settleCalls > 1,
          spend: {
            token_cost: null,
            compute_cost: null,
            token_status: "partial" as const,
            compute_status: "unavailable" as const,
            is_final: false,
          },
        };
      },
    );
    const proxy = new GatewayAccountingProxy({
      api: { gatewayUsage } as unknown as PostHogAPIClient,
      taskId: "task-example",
      runId: "run-example",
      upstreamUrl: upstream,
      upstreamBearer: "private-bearer",
      logger: { warn: vi.fn() } as never,
    });

    await proxy.start();
    await request(
      `${proxy.baseUrl}/v1/messages`,
      { authorization: `Bearer ${proxy.bearer}` },
      "POST",
    );
    await proxy.stop();

    expect(settleCalls).toBe(2);
  });

  it("retains a bound request after a transient bind failure", async () => {
    const upstream = await listen(
      http.createServer((_request, response) => {
        response.writeHead(200, { "x-request-id": "gateway-request" });
        response.end("ok");
      }),
    );
    let bindCalls = 0;
    let settled = false;
    const gatewayUsage = vi.fn(
      async (
        _task: string,
        _run: string,
        operation: { operation: string; request_id?: string },
      ) => {
        if (operation.operation === "request" && operation.request_id) {
          bindCalls += 1;
          if (bindCalls === 1) throw new Error("temporary failure");
        }
        if (operation.operation === "settle") settled = true;
        return {
          settled,
          spend: {
            token_cost: null,
            compute_cost: null,
            token_status: "partial" as const,
            compute_status: "unavailable" as const,
            is_final: false,
          },
        };
      },
    );
    const proxy = new GatewayAccountingProxy({
      api: { gatewayUsage } as unknown as PostHogAPIClient,
      taskId: "task-example",
      runId: "run-example",
      upstreamUrl: upstream,
      upstreamBearer: "private-bearer",
      logger: { warn: vi.fn() } as never,
    });

    await proxy.start();
    await request(
      `${proxy.baseUrl}/v1/messages`,
      { authorization: `Bearer ${proxy.bearer}` },
      "POST",
    );
    await proxy.stop();

    expect(bindCalls).toBe(2);
    expect(settled).toBe(true);
  });

  it("binds the upstream request ID before a stream closes and cancels the stream on shutdown", async () => {
    let resolveUpstreamClose: (() => void) | null = null;
    const upstreamClosed = new Promise<void>((resolve) => {
      resolveUpstreamClose = resolve;
    });
    const upstream = await listen(
      http.createServer((request, response) => {
        request.once("close", () => resolveUpstreamClose?.());
        response.writeHead(200, { "x-request-id": "gateway-request" });
        response.write("partial");
      }),
    );
    const gatewayUsage = vi.fn(
      async (
        _task: string,
        _run: string,
        _operation: { operation: string },
      ) => ({
        settled: true,
        spend: {
          token_cost: null,
          compute_cost: null,
          token_status: "partial" as const,
          compute_status: "unavailable" as const,
          is_final: false,
        },
      }),
    );
    const proxy = new GatewayAccountingProxy({
      api: { gatewayUsage } as unknown as PostHogAPIClient,
      taskId: "task-example",
      runId: "run-example",
      upstreamUrl: upstream,
      upstreamBearer: "private-bearer",
      logger: { warn: vi.fn() } as never,
    });

    await proxy.start();
    const clientResponse = new Promise<http.IncomingMessage>(
      (resolve, reject) => {
        const client = http.request(
          `${proxy.baseUrl}/v1/messages`,
          {
            headers: { authorization: `Bearer ${proxy.bearer}` },
            method: "POST",
          },
          resolve,
        );
        client.on("error", reject);
        client.end();
      },
    );
    const response = await clientResponse;
    response.resume();
    await vi.waitFor(() =>
      expect(
        gatewayUsage.mock.calls.some(
          (call) =>
            (call[2] as { operation: string; request_id?: string })
              .operation === "request" &&
            (call[2] as { request_id?: string }).request_id ===
              "gateway-request",
        ),
      ).toBe(true),
    );

    expect(
      gatewayUsage.mock.calls.some(
        (call) => (call[2] as { operation: string }).operation === "settle",
      ),
    ).toBe(false);

    await proxy.stop();
    await upstreamClosed;

    expect(
      gatewayUsage.mock.calls.map(
        (call) => (call[2] as { operation: string }).operation,
      ),
    ).toEqual(["start", "request", "request", "settle", "finish"]);
  });

  it("leaves an interrupted intent open without waiting for a deadline", async () => {
    const upstream = await listen(http.createServer());
    let intentStarted: (() => void) | null = null;
    const intentPending = new Promise<void>((resolve) => {
      intentStarted = resolve;
    });
    const gatewayUsage = vi.fn(
      async (
        _task: string,
        _run: string,
        operation: { operation: string; request_id?: string },
        signal?: AbortSignal,
      ) => {
        if (operation.operation === "request" && !operation.request_id) {
          intentStarted?.();
          await new Promise<void>((_resolve, reject) =>
            signal?.addEventListener(
              "abort",
              () => reject(new Error("aborted")),
              {
                once: true,
              },
            ),
          );
        }
        return {
          settled: true,
          spend: {
            token_cost: null,
            compute_cost: null,
            token_status: "partial" as const,
            compute_status: "unavailable" as const,
            is_final: false,
          },
        };
      },
    );
    const proxy = new GatewayAccountingProxy({
      api: { gatewayUsage } as unknown as PostHogAPIClient,
      taskId: "task-example",
      runId: "run-example",
      upstreamUrl: upstream,
      upstreamBearer: "private-bearer",
      logger: { warn: vi.fn() } as never,
    });

    await proxy.start();
    const client = http.request(`${proxy.baseUrl}/v1/messages`, {
      headers: { authorization: `Bearer ${proxy.bearer}` },
      method: "POST",
    });
    client.on("error", () => {});
    client.end();
    await intentPending;

    await proxy.stop();

    expect(
      gatewayUsage.mock.calls.map(
        (call) => (call[2] as { operation: string }).operation,
      ),
    ).toEqual(["start", "request"]);
  });

  it("does not finish an epoch when starting it fails", async () => {
    const gatewayUsage = vi.fn(async () => {
      throw new Error("start failed");
    });
    const proxy = new GatewayAccountingProxy({
      api: { gatewayUsage } as unknown as PostHogAPIClient,
      taskId: "task-example",
      runId: "run-example",
      upstreamUrl: "http://127.0.0.1:1",
      upstreamBearer: "private-bearer",
      logger: { warn: vi.fn() } as never,
    });

    await expect(proxy.start()).rejects.toThrow("start failed");
    await proxy.stop();

    expect(gatewayUsage).toHaveBeenCalledTimes(1);
  });

  it("proxies token-count helpers without creating spend intents", async () => {
    const upstream = await listen(
      http.createServer((_request, response) => response.end("{}")),
    );
    const gatewayUsage = vi.fn(async () => ({
      settled: true,
      spend: {
        token_cost: null,
        compute_cost: null,
        token_status: "unavailable" as const,
        compute_status: "unavailable" as const,
        is_final: false,
      },
    }));
    const proxy = new GatewayAccountingProxy({
      api: { gatewayUsage } as unknown as PostHogAPIClient,
      taskId: "task-example",
      runId: "run-example",
      upstreamUrl: upstream,
      upstreamBearer: "private-bearer",
      logger: { warn: vi.fn() } as never,
    });

    await proxy.start();
    await request(
      `${proxy.baseUrl}/v1/messages/count_tokens`,
      { authorization: `Bearer ${proxy.bearer}` },
      "POST",
    );
    await proxy.stop();

    expect(
      (
        gatewayUsage.mock.calls as unknown as Array<
          [string, string, { operation: string }]
        >
      ).map((call) => call[2].operation),
    ).toEqual(["start", "finish"]);
  });
});
