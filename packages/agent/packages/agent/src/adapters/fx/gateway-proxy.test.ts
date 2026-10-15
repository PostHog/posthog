import http from "node:http";
import type { AddressInfo } from "node:net";
import { afterEach, describe, expect, it } from "vitest";
import { Logger } from "../../utils/logger";
import { type FxGatewayProxy, startFxGatewayProxy } from "./gateway-proxy";

interface UpstreamRequest {
  method: string;
  url: string;
  headers: http.IncomingHttpHeaders;
  body: string;
}

const logger = new Logger({ debug: false, prefix: "[test]" });

let upstream: http.Server | null = null;
let proxy: FxGatewayProxy | null = null;

function streamTwoEvents(res: http.ServerResponse): void {
  res.writeHead(200, { "content-type": "text/event-stream" });
  res.write("data: one\n\n");
  res.end("data: [DONE]\n\n");
}

async function startUpstream(
  respond: (res: http.ServerResponse) => void = streamTwoEvents,
): Promise<{
  baseUrl: string;
  requests: UpstreamRequest[];
}> {
  const requests: UpstreamRequest[] = [];
  upstream = http.createServer((req, res) => {
    const chunks: Buffer[] = [];
    req.on("data", (chunk: Buffer) => chunks.push(chunk));
    req.on("end", () => {
      requests.push({
        method: req.method ?? "",
        url: req.url ?? "",
        headers: req.headers,
        body: Buffer.concat(chunks).toString(),
      });
      respond(res);
    });
  });
  await new Promise<void>((resolve) =>
    upstream?.listen(0, "127.0.0.1", resolve),
  );
  const { port } = upstream.address() as AddressInfo;
  return { baseUrl: `http://127.0.0.1:${port}/v1`, requests };
}

afterEach(async () => {
  await proxy?.stop();
  proxy = null;
  await new Promise<void>((resolve) => {
    if (!upstream) return resolve();
    upstream.closeAllConnections();
    upstream.close(() => resolve());
  });
  upstream = null;
});

describe("startFxGatewayProxy", () => {
  it("swaps the local key for the gateway credential and adds attribution headers", async () => {
    const { baseUrl, requests } = await startUpstream();
    proxy = await startFxGatewayProxy({
      upstreamBaseUrl: baseUrl,
      upstreamApiKey: "gateway-token",
      headers: { "X-PostHog-Properties": '{"task_runtime_adapter":"fx"}' },
      logger,
    });

    const response = await fetch(`${proxy.baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${proxy.apiKey}`,
        "content-type": "application/json",
      },
      body: JSON.stringify({ model: "gpt-6-sol", stream: true }),
    });

    expect(response.status).toBe(200);
    expect(await response.text()).toBe("data: one\n\ndata: [DONE]\n\n");
    expect(requests).toEqual([
      expect.objectContaining({
        method: "POST",
        url: "/v1/chat/completions",
        body: '{"model":"gpt-6-sol","stream":true}',
        headers: expect.objectContaining({
          authorization: "Bearer gateway-token",
          "x-posthog-properties": '{"task_runtime_adapter":"fx"}',
        }),
      }),
    ]);
  });

  it.each([
    {
      name: "a successful completion",
      status: 200,
      body: "data: [DONE]\n\n",
      reported: null,
    },
    {
      name: "a rate-limited completion",
      status: 429,
      body: '{"error":{"message":"slow down"}}',
      reported: 'API Error: 429 {"error":{"message":"slow down"}}',
    },
  ])(
    "reports $name to the adapter and still returns it to fx",
    async ({ status, body, reported }) => {
      const { baseUrl } = await startUpstream((res) => {
        res.writeHead(status);
        res.end(body);
      });
      const results: (string | null)[] = [];
      proxy = await startFxGatewayProxy({
        upstreamBaseUrl: baseUrl,
        upstreamApiKey: "gateway-token",
        headers: {},
        logger,
        onCompletionResult: (failure) => results.push(failure),
      });

      const response = await fetch(`${proxy.baseUrl}/chat/completions`, {
        method: "POST",
        headers: { authorization: `Bearer ${proxy.apiKey}` },
        body: "{}",
      });

      expect(response.status).toBe(status);
      expect(await response.text()).toBe(body);
      expect(results).toEqual([reported]);
    },
  );

  it("reports a stream that drops after the headers as a connection error", async () => {
    const { baseUrl } = await startUpstream((res) => {
      res.writeHead(200, { "content-type": "text/event-stream" });
      res.write("data: one\n\n", () => res.destroy());
    });
    const results: (string | null)[] = [];
    proxy = await startFxGatewayProxy({
      upstreamBaseUrl: baseUrl,
      upstreamApiKey: "gateway-token",
      headers: {},
      logger,
      onCompletionResult: (failure) => results.push(failure),
    });

    const response = await fetch(`${proxy.baseUrl}/chat/completions`, {
      method: "POST",
      headers: { authorization: `Bearer ${proxy.apiKey}` },
      body: "{}",
    });
    await response.text().catch(() => undefined);

    expect(results).toEqual(["API Error: Connection error"]);
  });

  it("sends response headers before the first event arrives", async () => {
    let finish = () => {};
    const { baseUrl } = await startUpstream((res) => {
      res.writeHead(200, { "content-type": "text/event-stream" });
      res.flushHeaders();
      finish = () => res.end("data: [DONE]\n\n");
    });
    proxy = await startFxGatewayProxy({
      upstreamBaseUrl: baseUrl,
      upstreamApiKey: "gateway-token",
      headers: {},
      logger,
    });

    const response = await fetch(`${proxy.baseUrl}/chat/completions`, {
      method: "POST",
      headers: { authorization: `Bearer ${proxy.apiKey}` },
      body: "{}",
    });
    finish();

    expect(response.status).toBe(200);
    expect(await response.text()).toBe("data: [DONE]\n\n");
  });

  it.each([
    {
      name: "a missing local key",
      path: "/v1/chat/completions",
      authorization: undefined,
      status: 401,
    },
    {
      name: "a wrong local key",
      path: "/v1/chat/completions",
      authorization: "Bearer not-the-key",
      status: 401,
    },
    {
      name: "a path outside the model API",
      path: "/v1/../api/projects",
      authorization: "valid",
      status: 404,
    },
    {
      name: "an unlisted gateway path",
      path: "/v1/messages",
      authorization: "valid",
      status: 404,
    },
    {
      name: "a malformed request target",
      path: "//[",
      authorization: "valid",
      status: 400,
    },
    {
      name: "a body over 16 MiB",
      path: "/v1/chat/completions",
      authorization: "valid",
      status: 413,
      body: "x".repeat(16 * 1024 * 1024 + 1),
    },
  ])(
    "rejects $name without calling the gateway",
    async ({ path, authorization, status, body = "{}" }) => {
      const { baseUrl, requests } = await startUpstream();
      proxy = await startFxGatewayProxy({
        upstreamBaseUrl: baseUrl,
        upstreamApiKey: "gateway-token",
        headers: {},
        logger,
      });
      const headers: Record<string, string> = {};
      if (authorization === "valid") {
        headers.authorization = `Bearer ${proxy.apiKey}`;
      } else if (authorization) {
        headers.authorization = authorization;
      }

      const response = await fetch(`${new URL(proxy.baseUrl).origin}${path}`, {
        method: "POST",
        headers,
        body,
      });

      expect(response.status).toBe(status);
      expect(requests).toEqual([]);
    },
  );
});
