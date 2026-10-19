/**
 * Loopback HTTP server that receives OAuth authorization-code redirects.
 *
 * Binds to 127.0.0.1 on an ephemeral port by default, or to the exact
 * host/port/path of a configured static redirect URL (required when the
 * OAuth client was pre-registered with a fixed redirect URI). Callbacks are
 * matched to in-flight flows by the OAuth `state` parameter (CSRF check).
 */

import type { IncomingMessage, Server, ServerResponse } from "node:http";
import { createServer } from "node:http";
import { McpError } from "./errors";

const DEFAULT_CALLBACK_PATH = "/callback";
/** How long to wait for the user to complete authorization in the browser. */
export const DEFAULT_CALLBACK_TIMEOUT_MS = 5 * 60 * 1000;

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function page(title: string, heading: string, body: string): string {
  return `<!DOCTYPE html>
<html>
<head><title>${escapeHtml(title)}</title>
<style>body{font-family:system-ui,sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}main{text-align:center}</style>
</head>
<body><main><h1>${escapeHtml(heading)}</h1><p>${escapeHtml(body)}</p></main></body>
</html>`;
}

interface PendingCallback {
  resolve: (code: string) => void;
  reject: (error: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

export interface CallbackEndpoint {
  /** Full redirect URL to hand to the authorization server. */
  redirectUrl: string;
  port: number;
}

interface ParsedRedirectUrl {
  hostname: string;
  port: number;
  path: string;
}

/** Validate a configured static redirect URL (loopback-only, explicit port). */
export function parseStaticRedirectUrl(redirectUrl: string): ParsedRedirectUrl {
  let url: URL;
  try {
    url = new URL(redirectUrl);
  } catch {
    throw new McpError(
      `Invalid OAuth redirectUrl: ${redirectUrl}`,
      "<oauth>",
      "config",
    );
  }
  const hostname = url.hostname.toLowerCase();
  const isLoopback =
    hostname === "localhost" ||
    hostname === "127.0.0.1" ||
    hostname === "[::1]";
  if (url.protocol !== "http:" || !isLoopback) {
    throw new McpError(
      "OAuth redirectUrl must be an http:// loopback URL",
      "<oauth>",
      "config",
    );
  }
  const port = Number.parseInt(url.port, 10);
  if (!Number.isInteger(port) || port <= 0 || port > 65535) {
    throw new McpError(
      "OAuth redirectUrl must include an explicit port",
      "<oauth>",
      "config",
    );
  }
  return {
    hostname: hostname === "[::1]" ? "::1" : hostname,
    port,
    path: url.pathname,
  };
}

export class CallbackServer {
  private server: Server | undefined;
  private endpoint: CallbackEndpoint | undefined;
  private path = DEFAULT_CALLBACK_PATH;
  private readonly pending = new Map<string, PendingCallback>();
  /** Serializes ensureStarted — concurrent callers must not double-bind. */
  private starting: Promise<CallbackEndpoint> | undefined;

  /**
   * Start (or reuse) the callback server and return its endpoint.
   * With `staticRedirectUrl` the server binds to that exact address and the
   * configured URL is returned verbatim.
   */
  async ensureStarted(staticRedirectUrl?: string): Promise<CallbackEndpoint> {
    while (this.starting) {
      await this.starting.catch(() => {
        // The failure belongs to the caller that initiated that bind.
      });
    }
    const operation = this.ensureStartedLocked(staticRedirectUrl);
    this.starting = operation;
    try {
      return await operation;
    } finally {
      this.starting = undefined;
    }
  }

  private async ensureStartedLocked(
    staticRedirectUrl?: string,
  ): Promise<CallbackEndpoint> {
    const target = staticRedirectUrl
      ? parseStaticRedirectUrl(staticRedirectUrl)
      : { hostname: "127.0.0.1", port: 0, path: DEFAULT_CALLBACK_PATH };

    if (this.server && this.endpoint) {
      const samePath = this.path === target.path;
      const samePort = target.port === 0 || this.endpoint.port === target.port;
      if (samePath && samePort) return this.endpoint;
      if (this.pending.size > 0) {
        throw new McpError(
          "OAuth callback server cannot rebind while an authorization is pending",
          "<oauth>",
          "connection",
        );
      }
      await this.stop();
    }

    const server = createServer((req, res) => this.handleRequest(req, res));
    await new Promise<void>((resolve, reject) => {
      server.once("error", reject);
      server.listen(target.port, target.hostname, () => resolve());
    });
    server.unref();

    const address = server.address();
    const port =
      typeof address === "object" && address !== null
        ? address.port
        : target.port;
    this.server = server;
    this.path = target.path;
    this.endpoint = {
      port,
      redirectUrl:
        staticRedirectUrl ?? `http://127.0.0.1:${port}${target.path}`,
    };
    return this.endpoint;
  }

  /**
   * Wait for the redirect carrying `state`. Register this BEFORE opening
   * the browser so a fast redirect cannot be missed.
   */
  waitForCallback(
    state: string,
    timeoutMs: number = DEFAULT_CALLBACK_TIMEOUT_MS,
  ): Promise<string> {
    return new Promise<string>((resolve, reject) => {
      const timer = setTimeout(() => {
        if (this.pending.delete(state)) {
          reject(
            new McpError(
              "OAuth callback timed out — authorization took too long",
              "<oauth>",
              "connection",
            ),
          );
        }
      }, timeoutMs);
      timer.unref?.();
      this.pending.set(state, { resolve, reject, timer });
    });
  }

  /** Cancel a pending flow (rejects its waitForCallback promise). */
  cancel(state: string): void {
    const pending = this.pending.get(state);
    if (!pending) return;
    this.pending.delete(state);
    clearTimeout(pending.timer);
    pending.reject(
      new McpError("Authorization cancelled", "<oauth>", "connection"),
    );
  }

  async stop(): Promise<void> {
    for (const state of [...this.pending.keys()]) this.cancel(state);
    const server = this.server;
    this.server = undefined;
    this.endpoint = undefined;
    this.path = DEFAULT_CALLBACK_PATH;
    if (server) {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  }

  private handleRequest(req: IncomingMessage, res: ServerResponse): void {
    const url = new URL(req.url ?? "/", "http://127.0.0.1");
    if (url.pathname !== this.path) {
      res.writeHead(404, { "Content-Type": "text/plain" });
      res.end("Not found");
      return;
    }

    const state = url.searchParams.get("state");
    const pending = state === null ? undefined : this.pending.get(state);
    if (state === null || !pending) {
      // Unknown or missing state: reject without disturbing real flows.
      res.writeHead(400, { "Content-Type": "text/html" });
      res.end(
        page(
          "Authorization failed",
          "Authorization failed",
          "Invalid or expired state parameter.",
        ),
      );
      return;
    }

    const error = url.searchParams.get("error");
    if (error) {
      const description = url.searchParams.get("error_description");
      const message = description ? `${error}: ${description}` : error;
      res.writeHead(200, { "Content-Type": "text/html" });
      res.end(page("Authorization failed", "Authorization failed", message));
      this.pending.delete(state);
      clearTimeout(pending.timer);
      pending.reject(new McpError(message, "<oauth>", "connection"));
      return;
    }

    const code = url.searchParams.get("code");
    if (!code) {
      // Known state but neither `error` nor `code`: a malformed redirect.
      // Reject the waiter now instead of leaving it to hang until the
      // 5-minute timeout with an unresponsive terminal.
      const message = "Authorization redirect missing code parameter.";
      res.writeHead(400, { "Content-Type": "text/html" });
      res.end(page("Authorization failed", "Authorization failed", message));
      this.pending.delete(state);
      clearTimeout(pending.timer);
      pending.reject(new McpError(message, "<oauth>", "connection"));
      return;
    }

    res.writeHead(200, { "Content-Type": "text/html" });
    res.end(
      page(
        "Authorization successful",
        "Authorization successful",
        "You can close this window and return to your terminal.",
      ),
    );
    this.pending.delete(state);
    clearTimeout(pending.timer);
    pending.resolve(code);
  }
}
