/**
 * MCP SDK `OAuthClientProvider` implementation backed by `McpAuthStorage`.
 *
 * Two usage modes:
 *   - Background (no `onRedirect`): attached to server transports so
 *     connections send stored access tokens and refresh them silently.
 *     If the SDK falls through to a fresh authorization (refresh failed,
 *     no tokens, no registered client), `clientInformation`/`state`/
 *     `redirectToAuthorization` throw `UnauthorizedError` instead of
 *     registering a client or opening a browser — the user is told to run
 *     `/mcp:auth <server>`. `redirectUrl` always returns a placeholder in
 *     this mode because the SDK treats a missing redirectUrl as a
 *     non-interactive (client_credentials-style) flow and would skip the
 *     refresh path entirely.
 *   - Interactive (with `onRedirect`, during `/mcp:auth`): the flow saves
 *     an `oauthState` first, and the provider forwards the authorization
 *     URL to the callback so the browser can be opened.
 */

import type { OAuthClientProvider } from "@modelcontextprotocol/sdk/client/auth.js";
import { UnauthorizedError } from "@modelcontextprotocol/sdk/client/auth.js";
import type {
  OAuthClientInformation,
  OAuthClientInformationFull,
  OAuthClientMetadata,
  OAuthTokens,
} from "@modelcontextprotocol/sdk/shared/auth.js";
import type { McpAuthStorage, StoredClientInfo } from "./auth-storage";
import type { McpAuthConfig } from "./config";

// Not "PostHog Code": PostHog's own OAuth server rejects dynamic client
// registrations whose name starts with "posthog" (anti-impersonation), and
// other servers may have similar rules. Overridable per server via
// `auth.clientName`.
const DEFAULT_CLIENT_NAME = "Code by PostHog";
const DEFAULT_CLIENT_URI = "https://posthog.com";

/**
 * Placeholder so the SDK never classifies a background provider as a
 * non-interactive flow (`!provider.redirectUrl` skips token refresh in
 * SDK `auth()`). It is never sent anywhere: background providers refuse
 * client registration and authorization redirects before it could be used.
 */
const BACKGROUND_REDIRECT_PLACEHOLDER = "http://127.0.0.1/mcp-auth-required";

export class McpOAuthProvider implements OAuthClientProvider {
  constructor(
    private readonly serverName: string,
    private readonly serverUrl: string,
    private readonly config: McpAuthConfig,
    private readonly storage: McpAuthStorage,
    /**
     * Interactive-flow callback receiving the authorization URL. Absent for
     * background providers, which must never open a browser.
     */
    private readonly onRedirect?: (url: URL) => void | Promise<void>,
    /**
     * Redirect URL for this flow (callback-server address). Falls back to
     * the configured static redirectUrl.
     */
    private readonly flowRedirectUrl?: string,
  ) {}

  get redirectUrl(): string {
    return (
      this.flowRedirectUrl ??
      this.config.redirectUrl ??
      BACKGROUND_REDIRECT_PLACEHOLDER
    );
  }

  get clientMetadata(): OAuthClientMetadata {
    return {
      redirect_uris: [this.redirectUrl],
      client_name: this.config.clientName ?? DEFAULT_CLIENT_NAME,
      client_uri: DEFAULT_CLIENT_URI,
      grant_types: ["authorization_code", "refresh_token"],
      response_types: ["code"],
      token_endpoint_auth_method: this.config.clientSecret
        ? "client_secret_post"
        : "none",
      ...(this.config.scope !== undefined ? { scope: this.config.scope } : {}),
    };
  }

  async state(): Promise<string> {
    const entry = await this.storage.readForUrl(
      this.serverName,
      this.serverUrl,
    );
    if (!entry?.oauthState) {
      throw new UnauthorizedError(
        `Authentication required for MCP server "${this.serverName}" — run /mcp:auth ${this.serverName}`,
      );
    }
    return entry.oauthState;
  }

  async clientInformation(): Promise<OAuthClientInformation | undefined> {
    // Pre-registered client from config wins.
    if (this.config.clientId) {
      return {
        client_id: this.config.clientId,
        ...(this.config.clientSecret !== undefined
          ? { client_secret: this.config.clientSecret }
          : {}),
      };
    }

    const entry = await this.storage.readForUrl(
      this.serverName,
      this.serverUrl,
    );
    const info = entry?.clientInfo;
    if (!info) {
      // Returning undefined makes the SDK run dynamic client registration.
      // A background provider must never do that: registering with the
      // placeholder redirect URI would poison the stored client for later
      // interactive flows on servers that enforce registered redirect URIs.
      if (!this.onRedirect) {
        throw new UnauthorizedError(
          `Authentication required for MCP server "${this.serverName}" — run /mcp:auth ${this.serverName}`,
        );
      }
      return undefined;
    }
    // Expired dynamic registrations force a fresh registration (interactive
    // mode only — background providers must not register).
    if (
      info.clientSecretExpiresAt !== undefined &&
      info.clientSecretExpiresAt !== 0 &&
      info.clientSecretExpiresAt < Date.now() / 1000
    ) {
      if (!this.onRedirect) {
        throw new UnauthorizedError(
          `Authentication required for MCP server "${this.serverName}" — run /mcp:auth ${this.serverName}`,
        );
      }
      return undefined;
    }
    return {
      client_id: info.clientId,
      ...(info.clientSecret !== undefined
        ? { client_secret: info.clientSecret }
        : {}),
    };
  }

  async saveClientInformation(info: OAuthClientInformationFull): Promise<void> {
    const clientInfo: StoredClientInfo = {
      clientId: info.client_id,
      ...(info.client_secret !== undefined
        ? { clientSecret: info.client_secret }
        : {}),
      ...(info.client_id_issued_at !== undefined
        ? { clientIdIssuedAt: info.client_id_issued_at }
        : {}),
      ...(info.client_secret_expires_at !== undefined
        ? { clientSecretExpiresAt: info.client_secret_expires_at }
        : {}),
      ...(info.redirect_uris !== undefined
        ? { redirectUris: info.redirect_uris.map(String) }
        : {}),
    };
    await this.storage.update(this.serverName, this.serverUrl, (entry) => {
      entry.clientInfo = clientInfo;
    });
  }

  async tokens(): Promise<OAuthTokens | undefined> {
    const entry = await this.storage.readForUrl(
      this.serverName,
      this.serverUrl,
    );
    const stored = entry?.tokens;
    if (!stored) return undefined;
    return {
      access_token: stored.accessToken,
      token_type: "Bearer",
      ...(stored.refreshToken !== undefined
        ? { refresh_token: stored.refreshToken }
        : {}),
      ...(stored.expiresAt !== undefined
        ? {
            expires_in: Math.max(
              0,
              Math.floor(stored.expiresAt - Date.now() / 1000),
            ),
          }
        : {}),
      ...(stored.scope !== undefined ? { scope: stored.scope } : {}),
    };
  }

  async saveTokens(tokens: OAuthTokens): Promise<void> {
    await this.storage.update(this.serverName, this.serverUrl, (entry) => {
      entry.tokens = {
        accessToken: tokens.access_token,
        ...(tokens.refresh_token !== undefined
          ? { refreshToken: tokens.refresh_token }
          : {}),
        ...(tokens.expires_in !== undefined
          ? { expiresAt: Date.now() / 1000 + tokens.expires_in }
          : {}),
        ...(tokens.scope !== undefined ? { scope: tokens.scope } : {}),
      };
      entry.savedAt = Date.now();
    });
  }

  async redirectToAuthorization(authorizationUrl: URL): Promise<void> {
    if (!this.onRedirect) {
      throw new UnauthorizedError(
        `Authentication required for MCP server "${this.serverName}" — run /mcp:auth ${this.serverName}`,
      );
    }
    // Guard against the SDK falling from a failed refresh into a fresh
    // authorization outside a user-initiated flow.
    const entry = await this.storage.readForUrl(
      this.serverName,
      this.serverUrl,
    );
    if (!entry?.oauthState) {
      throw new UnauthorizedError(
        `Authentication required for MCP server "${this.serverName}" — run /mcp:auth ${this.serverName}`,
      );
    }
    await this.onRedirect(authorizationUrl);
  }

  async saveCodeVerifier(codeVerifier: string): Promise<void> {
    await this.storage.update(this.serverName, this.serverUrl, (entry) => {
      entry.codeVerifier = codeVerifier;
    });
  }

  async codeVerifier(): Promise<string> {
    const entry = await this.storage.readForUrl(
      this.serverName,
      this.serverUrl,
    );
    if (!entry?.codeVerifier) {
      throw new Error(
        `No PKCE code verifier saved for MCP server "${this.serverName}"`,
      );
    }
    return entry.codeVerifier;
  }

  async invalidateCredentials(
    scope: "all" | "client" | "tokens" | "verifier" | "discovery",
  ): Promise<void> {
    switch (scope) {
      case "all":
        await this.storage.clear(this.serverName);
        break;
      case "client":
        await this.storage.clearFields(this.serverName, ["clientInfo"]);
        break;
      case "tokens":
        await this.storage.clearFields(this.serverName, ["tokens"]);
        break;
      case "verifier":
        await this.storage.clearFields(this.serverName, ["codeVerifier"]);
        break;
      case "discovery":
        // Discovery state is not persisted; nothing to invalidate.
        break;
    }
  }
}
