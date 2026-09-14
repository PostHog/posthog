import { randomBytes } from "node:crypto";
import type { IncomingHttpHeaders, Server } from "node:http";
import * as http from "node:http";
import * as https from "node:https";
import type { PostHogAPIClient } from "../posthog-api";
import type { Logger } from "../utils/logger";
import { GatewayUsageReporter } from "./run-usage";

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);
const MODEL_PATHS = new Set([
  "/v1/messages",
  "/v1/responses",
  "/responses",
  "/v1/chat/completions",
]);
const HELPER_METHODS = new Map([
  ["/v1/models", "GET"],
  ["/v1/messages/count_tokens", "POST"],
]);

export interface GatewayAccountingOptions {
  api: PostHogAPIClient;
  taskId: string;
  runId: string;
  upstreamUrl: string;
  upstreamBearer: string;
  logger: Logger;
}

function requestPath(request: http.IncomingMessage): string | null {
  if (
    !request.url ||
    !request.url.startsWith("/") ||
    request.url.startsWith("//")
  )
    return null;
  try {
    return new URL(request.url, "http://loopback").pathname;
  } catch {
    return null;
  }
}

function hopByHopHeaderNames(headers: IncomingHttpHeaders): Set<string> {
  const nominated = headers.connection;
  const values = Array.isArray(nominated) ? nominated : [nominated];
  return new Set(
    values
      .flatMap((value) => value?.split(",") ?? [])
      .map((value) => value.trim().toLowerCase()),
  );
}

function filteredHeaders(
  headers: IncomingHttpHeaders,
): http.OutgoingHttpHeaders {
  const nominated = hopByHopHeaderNames(headers);
  return Object.fromEntries(
    Object.entries(headers).filter(
      ([name, value]) =>
        value &&
        !HOP_BY_HOP_HEADERS.has(name.toLowerCase()) &&
        !nominated.has(name.toLowerCase()),
    ),
  );
}

function forwardedHeaders(
  headers: IncomingHttpHeaders,
  bearer: string,
): http.OutgoingHttpHeaders {
  const forwarded = filteredHeaders(headers);
  delete forwarded.authorization;
  delete forwarded["x-api-key"];
  delete forwarded.host;
  forwarded.authorization = `Bearer ${bearer}`;
  return forwarded;
}

function upstreamPath(upstream: URL, requestUrl: string): string {
  const prefix = upstream.pathname.replace(/\/$/, "").replace(/\/v1$/, "");
  return `${prefix}${requestUrl}`;
}

export class GatewayAccountingProxy {
  private readonly localBearer = randomBytes(32).toString("hex");
  private readonly upstream: URL;
  private server: Server | null = null;
  private port: number | null = null;
  private accepting = true;
  private readonly activeRequests = new Set<http.ClientRequest>();
  private readonly activeStreams = new Set<http.IncomingMessage>();
  private readonly dispatches = new Set<Promise<void>>();
  private readonly dispatchControllers = new Set<AbortController>();
  private readonly usageReporter: GatewayUsageReporter;

  constructor(private readonly options: GatewayAccountingOptions) {
    this.upstream = new URL(options.upstreamUrl);
    if (
      this.upstream.protocol !== "http:" &&
      this.upstream.protocol !== "https:"
    ) {
      throw new Error("gateway accounting requires an HTTP upstream");
    }
    this.usageReporter = new GatewayUsageReporter(
      options.api,
      options.taskId,
      options.runId,
      options.logger,
    );
  }

  get baseUrl(): string {
    if (this.port === null)
      throw new Error("gateway accounting proxy is not started");
    return `http://127.0.0.1:${this.port}`;
  }

  get bearer(): string {
    return this.localBearer;
  }

  async start(): Promise<void> {
    this.server = http.createServer((request, response) =>
      this.handle(request, response),
    );
    await new Promise<void>((resolve, reject) => {
      this.server?.once("error", reject);
      this.server?.listen(0, "127.0.0.1", () => {
        const address = this.server?.address();
        if (!address || typeof address === "string") {
          reject(new Error("gateway accounting proxy did not bind a TCP port"));
          return;
        }
        this.port = address.port;
        resolve();
      });
    });
  }

  async stop(): Promise<void> {
    this.accepting = false;
    this.server?.close();
    for (const controller of this.dispatchControllers) controller.abort();
    for (const request of this.activeRequests) request.destroy();
    for (const stream of this.activeStreams) stream.destroy();
    await Promise.allSettled([...this.dispatches]);
    await this.usageReporter.stop();
    this.server = null;
    this.port = null;
  }

  private trackDispatch(dispatch: Promise<void>): void {
    this.dispatches.add(dispatch);
    void dispatch.finally(() => this.dispatches.delete(dispatch));
  }

  private handle(
    request: http.IncomingMessage,
    response: http.ServerResponse,
  ): void {
    const path = requestPath(request);
    const isModelRequest =
      request.method === "POST" && path !== null && MODEL_PATHS.has(path);
    const isHelperRequest =
      path !== null && HELPER_METHODS.get(path) === request.method;
    if (!this.accepting || (!isModelRequest && !isHelperRequest)) {
      response.writeHead(this.accepting ? 404 : 503).end();
      request.resume();
      return;
    }
    const localCredential =
      request.headers.authorization ?? request.headers["x-api-key"];
    if (
      localCredential !== `Bearer ${this.localBearer}` &&
      localCredential !== this.localBearer
    ) {
      response.writeHead(401).end();
      request.resume();
      return;
    }
    this.trackDispatch(this.dispatch(request, response, isModelRequest));
  }

  private async dispatch(
    request: http.IncomingMessage,
    response: http.ServerResponse,
    isModelRequest: boolean,
  ): Promise<void> {
    const controller = new AbortController();
    let requestIdCaptured = false;
    this.dispatchControllers.add(controller);
    const abort = (): void => controller.abort();
    const abortOnClose = (): void => {
      if (!response.writableEnded) abort();
    };
    request.once("aborted", abort);
    response.once("close", abortOnClose);
    try {
      const transport = this.upstream.protocol === "https:" ? https : http;
      const { upstreamRequest, upstreamResponse } = await new Promise<{
        upstreamRequest: http.ClientRequest;
        upstreamResponse: http.IncomingMessage;
      }>((resolve, reject) => {
        const upstreamRequest = transport.request(
          {
            protocol: this.upstream.protocol,
            hostname: this.upstream.hostname,
            port: this.upstream.port || undefined,
            method: request.method,
            path: upstreamPath(this.upstream, request.url ?? "/"),
            headers: forwardedHeaders(
              request.headers,
              this.options.upstreamBearer,
            ),
          },
          (upstreamResponse) => resolve({ upstreamRequest, upstreamResponse }),
        );
        this.activeRequests.add(upstreamRequest);
        controller.signal.addEventListener(
          "abort",
          () => upstreamRequest.destroy(),
          { once: true },
        );
        upstreamRequest.once("error", (error) => {
          this.activeRequests.delete(upstreamRequest);
          reject(error);
        });
        request.pipe(upstreamRequest);
      });
      this.activeStreams.add(upstreamResponse);
      const streamFinished = new Promise<void>((resolve) => {
        upstreamResponse.once("end", resolve);
        upstreamResponse.once("close", resolve);
        upstreamResponse.once("error", resolve);
        response.once("close", resolve);
      });
      const requestFinished = new Promise<void>((resolve) => {
        upstreamRequest.once("close", resolve);
        upstreamRequest.once("error", resolve);
      });
      response.once("close", () => upstreamResponse.destroy());
      const header = upstreamResponse.headers["x-request-id"];
      const requestId = Array.isArray(header) ? header[0] : header;
      if (isModelRequest) {
        if (requestId) {
          requestIdCaptured = true;
          this.usageReporter.reportRequestId(requestId);
        } else this.options.logger.warn("Gateway response missing request ID");
      }
      response.writeHead(
        upstreamResponse.statusCode ?? 502,
        filteredHeaders(upstreamResponse.headers),
      );
      upstreamResponse.pipe(response);
      await Promise.all([streamFinished, requestFinished]);
      this.activeStreams.delete(upstreamResponse);
      this.activeRequests.delete(upstreamRequest);
    } catch (error) {
      if (isModelRequest && !requestIdCaptured)
        this.options.logger.warn("Gateway response missing request ID");
      if (!response.headersSent) response.writeHead(502);
      response.end();
      if (!controller.signal.aborted)
        this.options.logger.warn("Gateway proxy request failed", error);
    } finally {
      request.off("aborted", abort);
      response.off("close", abortOnClose);
      this.dispatchControllers.delete(controller);
    }
  }
}
