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

function createProxy(
  upstreamUrl: string,
  updateTaskRun = vi.fn(async () => ({})),
): {
  proxy: GatewayAccountingProxy;
  updateTaskRun: ReturnType<typeof vi.fn>;
  warn: ReturnType<typeof vi.fn>;
} {
  const warn = vi.fn();
  return {
    proxy: new GatewayAccountingProxy({
      api: { updateTaskRun } as unknown as PostHogAPIClient,
      taskId: "task-example",
      runId: "run-example",
      upstreamUrl,
      upstreamBearer: "private-bearer",
      logger: { warn } as never,
    }),
    updateTaskRun,
    warn,
  };
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
  it("forwards compressed model bytes with fixed auth and reports the request ID through task-run PATCH", async () => {
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
        const body = gzipSync("compressed upstream body");
        response.writeHead(200, {
          "content-encoding": "gzip",
          "content-length": body.length,
          "x-request-id": "gateway-request",
        });
        response.end(body);
      }),
    );
    const { proxy, updateTaskRun } = createProxy(`${upstream}/v1`);

    await proxy.start();
    const body = await request(
      `${proxy.baseUrl}/v1/messages`,
      {
        "x-api-key": proxy.bearer,
        connection: "x-remove-me",
        "x-remove-me": "secret",
      },
      "POST",
    );
    await proxy.stop();

    expect(body).toEqual(gzipSync("compressed upstream body"));
    expect(observed).toEqual({
      authorization: "Bearer private-bearer",
      xApiKey: undefined,
      nominated: undefined,
      url: "/v1/messages",
    });
    expect(updateTaskRun).toHaveBeenCalledExactlyOnceWith(
      "task-example",
      "run-example",
      { state_append: { unprocessed_request_ids: "gateway-request" } },
      expect.any(AbortSignal),
    );
  });

  it("retries only the task-run request-ID PATCH, allowing backend deduplication", async () => {
    const upstream = await listen(
      http.createServer((_request, response) => {
        response.writeHead(200, { "x-request-id": "gateway-request" });
        response.end("ok");
      }),
    );
    const updateTaskRun = vi
      .fn()
      .mockRejectedValueOnce(new Error("temporary failure"))
      .mockResolvedValue({});
    const { proxy } = createProxy(upstream, updateTaskRun);

    await proxy.start();
    await request(
      `${proxy.baseUrl}/v1/messages`,
      { authorization: `Bearer ${proxy.bearer}` },
      "POST",
    );
    await proxy.stop();

    expect(updateTaskRun).toHaveBeenCalledTimes(2);
    expect(updateTaskRun.mock.calls.map((call) => call[2])).toEqual([
      { state_append: { unprocessed_request_ids: "gateway-request" } },
      { state_append: { unprocessed_request_ids: "gateway-request" } },
    ]);
  });

  it("captures the request ID before a streaming response is cancelled", async () => {
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
    const { proxy, updateTaskRun } = createProxy(upstream);

    await proxy.start();
    const response = await new Promise<http.IncomingMessage>(
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
    response.resume();
    await vi.waitFor(() => expect(updateTaskRun).toHaveBeenCalledOnce());
    await proxy.stop();
    await upstreamClosed;

    expect(updateTaskRun).toHaveBeenCalledWith(
      "task-example",
      "run-example",
      { state_append: { unprocessed_request_ids: "gateway-request" } },
      expect.any(AbortSignal),
    );
  });

  it("cancels upstream before response headers without reporting a request ID", async () => {
    const received = Promise.withResolvers<void>();
    const closed = Promise.withResolvers<void>();
    const upstream = await listen(
      http.createServer((_request, response) => {
        response.once("close", () => closed.resolve());
        received.resolve();
      }),
    );
    const { proxy, updateTaskRun, warn } = createProxy(upstream);
    await proxy.start();
    const client = http.request(`${proxy.baseUrl}/v1/messages`, {
      method: "POST",
      headers: { authorization: `Bearer ${proxy.bearer}` },
    });
    client.on("error", () => {});
    client.end();
    await received.promise;
    client.destroy();
    await closed.promise;
    await proxy.stop();

    expect(updateTaskRun).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalledWith("Gateway response missing request ID");
  });

  it("logs a missing request ID without writing task-run state", async () => {
    const upstream = await listen(
      http.createServer((_request, response) => response.end("ok")),
    );
    const { proxy, updateTaskRun, warn } = createProxy(upstream);

    await proxy.start();
    await request(
      `${proxy.baseUrl}/v1/messages`,
      { authorization: `Bearer ${proxy.bearer}` },
      "POST",
    );
    await proxy.stop();

    expect(updateTaskRun).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalledWith("Gateway response missing request ID");
  });

  it("does not call the task-run API when no model request is proxied", async () => {
    const upstream = await listen(
      http.createServer((_request, response) => response.end("{}")),
    );
    const { proxy, updateTaskRun } = createProxy(upstream);

    await proxy.start();
    await proxy.stop();

    expect(updateTaskRun).not.toHaveBeenCalled();
  });

  it("proxies helpers without reporting usage", async () => {
    const upstream = await listen(
      http.createServer((_request, response) => response.end("{}")),
    );
    const { proxy, updateTaskRun } = createProxy(upstream);

    await proxy.start();
    await request(
      `${proxy.baseUrl}/v1/messages/count_tokens`,
      { authorization: `Bearer ${proxy.bearer}` },
      "POST",
    );
    await proxy.stop();

    expect(updateTaskRun).not.toHaveBeenCalled();
  });
});
