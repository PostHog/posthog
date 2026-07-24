/**
 * MCP Sandbox protocol handler.
 *
 * Serves the sandbox proxy HTML on `mcp-sandbox://proxy`, giving it an
 * isolated origin separate from the Electron renderer. This prevents
 * MCP Apps (running in the inner iframe) from accessing the host's DOM,
 * storage, or cookies via `window.parent.parent`.
 *
 * The scheme must be registered with `protocol.registerSchemesAsPrivileged`
 * BEFORE `app.ready` (done in bootstrap.ts). This handler is registered
 * AFTER `app.ready`.
 *
 * The proxy HTML is host-agnostic and lives in `@posthog/shared`; this is the
 * Electron-specific seam that serves it at an isolated origin. Web supplies the
 * same HTML via a blob URL (see the web composition root).
 */

import { sandboxProxyHtml } from "@posthog/shared/mcp-sandbox-proxy";
import { session } from "electron";

import { logger } from "../utils/logger";

const log = logger.scope("mcp-sandbox protocol");

/**
 * Register the mcp-sandbox: protocol handler on the "persist:main" session
 * (which the BrowserWindow uses). Must be called after app.ready.
 *
 * Note: `protocol.registerSchemesAsPrivileged()` is global and must be
 * called before app.ready — that's done separately in bootstrap.ts.
 */
export function registerMcpSandboxProtocol(): void {
  const mainSession = session.fromPartition("persist:main");

  mainSession.protocol.handle("mcp-sandbox", (request) => {
    log.debug("Serving proxy HTML", { url: request.url });

    return new Response(sandboxProxyHtml, {
      headers: { "Content-Type": "text/html; charset=utf-8" },
    });
  });
}
