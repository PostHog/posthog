import { randomBytes, timingSafeEqual } from "node:crypto";
import http from "node:http";
import type { AddressInfo } from "node:net";
import { Readable } from "node:stream";
import type { ReadableStream as NodeWebReadableStream } from "node:stream/web";
import type { Logger } from "../../utils/logger";

const FORWARDED_PATHS = new Set(["/chat/completions", "/models"]);
const MAX_BODY_BYTES = 16 * 1024 * 1024;
const DROPPED_RESPONSE_HEADERS = new Set([
  "connection",
  "content-encoding",
  "content-length",
  "keep-alive",
  "set-cookie",
  "transfer-encoding",
]);

export interface FxGatewayProxyOptions {
  upstreamBaseUrl: string;
  upstreamApiKey: string;
  headers: Record<string, string>;
  logger: Logger;
  onCompletionResult?: (failure: string | null) => void;
}

export interface FxGatewayProxy {
  baseUrl: string;
  apiKey: string;
  stop: () => Promise<void>;
}

class BodyTooLargeError extends Error {}

function readBody(req: http.IncomingMessage): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let size = 0;
    const onData = (chunk: Buffer) => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        req.off("data", onData);
        req.resume();
        reject(new BodyTooLargeError());
        return;
      }
      chunks.push(chunk);
    };
    req.on("data", onData);
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

function hasBearer(req: http.IncomingMessage, expected: Buffer): boolean {
  const header = req.headers.authorization;
  if (!header?.startsWith("Bearer ")) return false;
  const presented = Buffer.from(header.slice("Bearer ".length));
  return (
    presented.length === expected.length && timingSafeEqual(presented, expected)
  );
}

function sendError(
  res: http.ServerResponse,
  status: number,
  message: string,
): void {
  if (res.headersSent) {
    res.end();
    return;
  }
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify({ error: { message } }));
}

// fx custom connections cannot send extra headers, so attribution and the real credential are added here.
export async function startFxGatewayProxy(
  options: FxGatewayProxyOptions,
): Promise<FxGatewayProxy> {
  const apiKey = randomBytes(32).toString("base64url");
  const expectedKey = Buffer.from(apiKey);
  const upstreamBaseUrl = options.upstreamBaseUrl.replace(/\/$/, "");
  const { logger } = options;

  const forward = async (
    req: http.IncomingMessage,
    res: http.ServerResponse,
  ): Promise<void> => {
    if (!hasBearer(req, expectedKey)) {
      sendError(res, 401, "Unauthorized");
      return;
    }
    const url = URL.parse(req.url ?? "/", "http://127.0.0.1");
    if (!url) {
      sendError(res, 400, "Bad request");
      return;
    }
    const path = url.pathname.replace(/^\/v1(?=\/)/, "");
    if (!FORWARDED_PATHS.has(path)) {
      sendError(res, 404, "Not found");
      return;
    }

    const reportCompletion = (failure: string | null) => {
      if (path === "/chat/completions") options.onCompletionResult?.(failure);
    };
    const method = req.method ?? "GET";
    let body: Buffer | undefined;
    if (method !== "GET" && method !== "HEAD") {
      try {
        body = await readBody(req);
      } catch (error) {
        if (error instanceof BodyTooLargeError) {
          sendError(res, 413, "request body too large");
        } else {
          sendError(res, 400, "request body not received");
        }
        return;
      }
    }

    const abort = new AbortController();
    res.on("close", () => {
      if (!res.writableEnded) abort.abort();
    });

    const headers: Record<string, string> = {
      ...options.headers,
      authorization: `Bearer ${options.upstreamApiKey}`,
    };
    for (const name of ["content-type", "accept"] as const) {
      const value = req.headers[name];
      if (typeof value === "string") headers[name] = value;
    }

    try {
      const response = await fetch(`${upstreamBaseUrl}${path}${url.search}`, {
        method,
        headers,
        body: body && new Uint8Array(body),
        signal: abort.signal,
        redirect: "manual",
      });
      const responseHeaders: Record<string, string> = {};
      response.headers.forEach((value, name) => {
        if (!DROPPED_RESPONSE_HEADERS.has(name)) responseHeaders[name] = value;
      });
      if (response.status >= 400) {
        const text = await response.text();
        reportCompletion(`API Error: ${response.status} ${text}`);
        res.writeHead(response.status, responseHeaders);
        res.end(text);
        return;
      }
      res.writeHead(response.status, responseHeaders);
      if (!response.body) {
        reportCompletion(null);
        res.end();
        return;
      }
      res.flushHeaders();
      Readable.fromWeb(response.body as NodeWebReadableStream<Uint8Array>)
        .on("error", () => {
          if (!abort.signal.aborted) {
            reportCompletion("API Error: Connection error");
          }
          res.destroy();
        })
        .on("end", () => reportCompletion(null))
        .pipe(res);
    } catch (error) {
      if (abort.signal.aborted) return;
      logger.warn("fx gateway proxy forward failed", {
        path,
        error: error instanceof Error ? error.message : String(error),
      });
      reportCompletion("API Error: Connection error");
      sendError(res, 502, "PostHog gateway request failed");
    }
  };

  const server = http.createServer((req, res) => {
    void forward(req, res);
  });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      server.off("error", reject);
      resolve();
    });
  });
  const { port } = server.address() as AddressInfo;

  return {
    baseUrl: `http://127.0.0.1:${port}/v1`,
    apiKey,
    stop: () =>
      new Promise<void>((resolve) => {
        server.closeAllConnections();
        server.close(() => resolve());
      }),
  };
}
