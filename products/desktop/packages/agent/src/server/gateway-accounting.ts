import { randomBytes, randomUUID } from "node:crypto";
import type { IncomingHttpHeaders, Server } from "node:http";
import * as http from "node:http";
import * as https from "node:https";
import type { PostHogAPIClient } from "../posthog-api";
import type { Logger } from "../utils/logger";

const REPORT_DEADLINE_MS = 5_000;
const MAX_CONCURRENT_REPORTS = 4;
const RETRY_DELAYS_MS = [100, 250, 500];
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

function delay(milliseconds: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) return Promise.resolve();
  return new Promise((resolve) => {
    const finish = (): void => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    };
    const onAbort = (): void => {
      clearTimeout(timer);
      finish();
    };
    const timer = setTimeout(finish, milliseconds);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
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
  private readonly epochId = randomUUID();
  private readonly upstream: URL;
  private server: Server | null = null;
  private port: number | null = null;
  private accepting = true;
  private readonly activeRequests = new Set<http.ClientRequest>();
  private readonly activeStreams = new Set<http.IncomingMessage>();
  private readonly dispatches = new Set<Promise<void>>();
  private readonly dispatchControllers = new Set<AbortController>();
  private readonly reportController = new AbortController();
  private readonly uncertainIntents = new Set<string>();
  private readonly reports = new Set<Promise<void>>();
  private readonly queuedReports: Array<() => Promise<void>> = [];
  private activeReportCount = 0;
  private epochStarted = false;

  constructor(private readonly options: GatewayAccountingOptions) {
    this.upstream = new URL(options.upstreamUrl);
    if (
      this.upstream.protocol !== "http:" &&
      this.upstream.protocol !== "https:"
    ) {
      throw new Error("gateway accounting requires an HTTP upstream");
    }
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
    await this.callUsage({ operation: "start", epoch_id: this.epochId });
    this.epochStarted = true;
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
    const drained = await this.drainWork();
    if (drained) {
      if (this.epochStarted) {
        try {
          await this.callUsage({ operation: "finish", epoch_id: this.epochId });
        } catch (error) {
          this.options.logger.warn(
            "Failed to finish gateway accounting",
            error,
          );
        }
      }
    } else {
      this.options.logger.warn(
        "Gateway accounting still has pending work; leaving epoch open",
      );
    }
    this.server = null;
    this.port = null;
  }

  private async callUsage(
    operation: Parameters<PostHogAPIClient["gatewayUsage"]>[2],
    signal?: AbortSignal,
  ) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REPORT_DEADLINE_MS);
    try {
      return await this.options.api.gatewayUsage(
        this.options.taskId,
        this.options.runId,
        operation,
        AbortSignal.any([controller.signal, ...(signal ? [signal] : [])]),
      );
    } finally {
      clearTimeout(timer);
    }
  }

  private trackDispatch(dispatch: Promise<void>): void {
    this.dispatches.add(dispatch);
    void dispatch.finally(() => this.dispatches.delete(dispatch));
  }

  private trackReport(task: () => Promise<void>): void {
    this.queuedReports.push(task);
    this.runReports();
  }

  private runReports(): void {
    while (
      this.activeReportCount < MAX_CONCURRENT_REPORTS &&
      this.queuedReports.length > 0
    ) {
      const task = this.queuedReports.shift();
      if (!task) return;
      this.activeReportCount += 1;
      const report = task()
        .catch((error: unknown) =>
          this.options.logger.warn("Failed to report gateway usage", error),
        )
        .finally(() => {
          this.activeReportCount -= 1;
          this.reports.delete(report);
          this.runReports();
        });
      this.reports.add(report);
    }
  }

  private async drainWork(): Promise<boolean> {
    const deadline = Date.now() + REPORT_DEADLINE_MS;
    this.runReports();
    while (
      (this.dispatches.size > 0 ||
        this.uncertainIntents.size > 0 ||
        this.reports.size > 0 ||
        this.queuedReports.length > 0) &&
      Date.now() < deadline
    ) {
      const activeWork = [...this.dispatches, ...this.reports];
      if (activeWork.length === 0 || this.reportController.signal.aborted)
        return false;
      const waitController = new AbortController();
      const workSettled = Promise.allSettled(activeWork).finally(() =>
        waitController.abort(),
      );
      await Promise.race([
        workSettled,
        delay(
          Math.max(1, deadline - Date.now()),
          AbortSignal.any([
            waitController.signal,
            this.reportController.signal,
          ]),
        ),
      ]);
      this.runReports();
    }
    const complete =
      this.dispatches.size === 0 &&
      this.uncertainIntents.size === 0 &&
      this.reports.size === 0 &&
      this.queuedReports.length === 0;
    if (!complete) {
      this.reportController.abort();
      await Promise.allSettled([...this.dispatches, ...this.reports]);
    }
    return complete;
  }

  private async bindRequest(
    attemptId: string,
    requestId: string,
  ): Promise<boolean> {
    for (const retryDelay of RETRY_DELAYS_MS) {
      if (this.reportController.signal.aborted) return false;
      try {
        await this.callUsage(
          {
            operation: "request",
            epoch_id: this.epochId,
            attempt_id: attemptId,
            request_id: requestId,
          },
          this.reportController.signal,
        );
        return true;
      } catch {
        await delay(retryDelay, this.reportController.signal);
      }
    }
    return false;
  }

  private async settleRequest(
    attemptId: string,
    requestId: string,
  ): Promise<void> {
    for (const retryDelay of RETRY_DELAYS_MS) {
      if (this.reportController.signal.aborted) return;
      try {
        const result = await this.callUsage(
          {
            operation: "settle",
            epoch_id: this.epochId,
            attempt_id: attemptId,
            request_id: requestId,
          },
          this.reportController.signal,
        );
        if (result.settled) return;
      } catch {}
      await delay(retryDelay, this.reportController.signal);
    }
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
    this.dispatchControllers.add(controller);
    const attemptId = randomUUID();
    try {
      if (isModelRequest) {
        this.uncertainIntents.add(attemptId);
        await this.callUsage(
          {
            operation: "request",
            epoch_id: this.epochId,
            attempt_id: attemptId,
          },
          controller.signal,
        );
        this.uncertainIntents.delete(attemptId);
        if (!this.accepting || controller.signal.aborted) return;
      }
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
      const requestId = upstreamResponse.headers["x-request-id"];
      const id = Array.isArray(requestId) ? requestId[0] : requestId;
      response.writeHead(
        upstreamResponse.statusCode ?? 502,
        filteredHeaders(upstreamResponse.headers),
      );
      upstreamResponse.pipe(response);
      if (isModelRequest && id) {
        this.trackReport(async () => {
          if (!(await this.bindRequest(attemptId, id))) return;
          void streamFinished.then(() =>
            this.trackReport(() => this.settleRequest(attemptId, id)),
          );
        });
      }
      await Promise.all([streamFinished, requestFinished]);
      this.activeStreams.delete(upstreamResponse);
      this.activeRequests.delete(upstreamRequest);
    } catch (error) {
      if (!controller.signal.aborted) this.uncertainIntents.delete(attemptId);
      if (!response.headersSent) response.writeHead(502);
      response.end();
      if (!controller.signal.aborted)
        this.options.logger.warn(
          "Failed to record gateway request intent",
          error,
        );
    } finally {
      this.dispatchControllers.delete(controller);
    }
  }
}
