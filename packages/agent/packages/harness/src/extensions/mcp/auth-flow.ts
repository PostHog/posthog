/**
 * Interactive OAuth flow orchestration for `/mcp:auth`.
 *
 * Uses the MCP SDK's `auth()` as the single entry point: it performs
 * RFC 9728 / authorization-server metadata discovery, dynamic client
 * registration, and PKCE, then either completes silently with stored or
 * refreshed tokens ("authorized") or produces an authorization URL. In the
 * latter case we open the browser, wait for the loopback redirect, and
 * exchange the code via `transport.finishAuth()` ("completed").
 */

import { webcrypto } from "node:crypto";
import { auth } from "@modelcontextprotocol/sdk/client/auth.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import type { McpAuthStorage } from "./auth-storage";
import type { CallbackServer } from "./callback-server";
import type { McpAuthConfig } from "./config";
import { McpError } from "./errors";
import { McpOAuthProvider } from "./oauth-provider";

export type OAuthFlowResult =
  /** Valid (or refreshable) credentials already existed; no browser needed. */
  | "authorized"
  /** Full browser flow ran and tokens were exchanged. */
  | "completed";

export interface OAuthFlowParams {
  serverName: string;
  serverUrl: string;
  auth: McpAuthConfig;
  storage: McpAuthStorage;
  callbackServer: CallbackServer;
  /** Open a URL in the user's browser. Failures are non-fatal (headless). */
  openUrl: (url: string) => Promise<void>;
  /** Surface the authorization URL so remote/headless users can copy it. */
  onAuthorizationUrl?: (url: string) => void;
  /** How long to wait for the browser redirect. */
  timeoutMs?: number;
}

/** Generate a cryptographically secure OAuth `state` parameter. */
export function generateState(): string {
  return Array.from(webcrypto.getRandomValues(new Uint8Array(32)))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export type OAuthFlowRunner = (
  params: OAuthFlowParams,
) => Promise<OAuthFlowResult>;

export const runOAuthFlow: OAuthFlowRunner = async (params) => {
  const { serverName, serverUrl, storage, callbackServer } = params;

  const endpoint = await callbackServer.ensureStarted(params.auth.redirectUrl);
  const state = generateState();
  // Persisting the state marks a user-initiated flow: it authorizes
  // McpOAuthProvider.redirectToAuthorization/state for this server.
  await storage.update(serverName, serverUrl, (entry) => {
    entry.oauthState = state;
  });

  let authorizationUrl: URL | undefined;
  const provider = new McpOAuthProvider(
    serverName,
    serverUrl,
    params.auth,
    storage,
    (url) => {
      authorizationUrl = url;
    },
    endpoint.redirectUrl,
  );

  try {
    const result = await auth(provider, { serverUrl });
    if (result === "AUTHORIZED") return "authorized";

    if (!authorizationUrl) {
      throw new McpError(
        "Authorization server did not produce an authorization URL",
        serverName,
        "protocol",
      );
    }

    // Register the waiter BEFORE opening the browser so a fast redirect
    // cannot be missed.
    const callbackPromise = callbackServer.waitForCallback(
      state,
      params.timeoutMs,
    );
    // The browser can deliver an error redirect while `openUrl` is still
    // being awaited; mark the promise handled so that never surfaces as an
    // unhandled rejection (it is still awaited below).
    callbackPromise.catch(() => {});

    params.onAuthorizationUrl?.(authorizationUrl.toString());
    try {
      await params.openUrl(authorizationUrl.toString());
    } catch {
      // Headless / no browser: the URL was surfaced above; keep waiting.
    }

    let code: string;
    try {
      code = await callbackPromise;
    } catch (err) {
      callbackServer.cancel(state);
      throw err;
    }

    // finishAuth runs the code exchange (PKCE verifier + client auth) and
    // saves the tokens through the provider. The transport type does not
    // matter here; it is only a vehicle for the token request.
    const transport = new StreamableHTTPClientTransport(new URL(serverUrl), {
      authProvider: provider,
    });
    try {
      await transport.finishAuth(code);
    } finally {
      await transport.close().catch(() => {});
    }
    return "completed";
  } finally {
    // The state marker only authorizes this one interactive flow, and the
    // PKCE verifier is single-use — neither should outlive the flow on disk.
    await storage.clearFields(serverName, ["oauthState", "codeVerifier"]);
  }
};
