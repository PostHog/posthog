import type { IAuthOAuthFlowService } from "@posthog/core/auth/identifiers";
import {
  type CancelFlowOutput,
  type OAuthErrorCode,
  type OAuthTokenResponse,
  oAuthTokenResponse,
  type RefreshTokenOutput,
  type StartFlowOutput,
} from "@posthog/core/auth/oauth.schemas";
import type { RootLogger } from "@posthog/di/logger";
import {
  type CloudRegion,
  getCloudUrlFromRegion,
  getOauthClientIdFromRegion,
  OAUTH_SCOPES,
} from "@posthog/shared";

// Browser implementation of the auth OAuth flow. Desktop's OAuthService drives
// PKCE through a posthog-code:// deep link (prod) or a loopback HTTP server
// (dev); neither exists in a browser. Here the authorize page opens in a
// popup, the OAuth server redirects it back to /oauth/callback on this origin,
// and the callback page relays code+state to this (still-running) tab over a
// BroadcastChannel. Token exchange and refresh are the same plain fetches
// desktop makes.
//
// CORS on /oauth/token and /api/* is open (verified against us.posthog.com),
// so the only external requirement is redirect URI registration on the Code
// ("Array") OAuth application. The path is /callback to match the portless
// localhost convention: PostHog's authorize view extends RFC 8252 §7.3 port
// flexibility to `localhost`, so a registered `http://localhost/callback`
// matches this app on any dev port. Production needs
// `https://<web-origin>/callback` registered once a web origin exists. Until
// registration, the flow fails at the authorize step with a visible error.

export const OAUTH_CALLBACK_PATH = "/callback";
const OAUTH_CALLBACK_CHANNEL = "posthog-code:oauth-callback";

const FLOW_TIMEOUT_MS = 5 * 60 * 1000;
const TOKEN_FETCH_TIMEOUT_MS = 30_000;
const POPUP_FEATURES = "popup,width=600,height=760";

interface OAuthCallbackMessage {
  code: string | null;
  state: string | null;
  error: string | null;
}

class HttpError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

export function getWebRedirectUri(): string {
  return `${window.location.origin}${OAUTH_CALLBACK_PATH}`;
}

export class WebOAuthFlowService implements IAuthOAuthFlowService {
  private pendingFlow: { cancel: (reason: string) => void } | null = null;

  constructor(private readonly log: RootLogger) {}

  startFlow(region: CloudRegion): Promise<StartFlowOutput> {
    return this.runFlow(region, "login");
  }

  startSignupFlow(region: CloudRegion): Promise<StartFlowOutput> {
    return this.runFlow(region, "signup");
  }

  async refreshToken(
    refreshToken: string,
    region: CloudRegion,
  ): Promise<RefreshTokenOutput> {
    try {
      const data = await this.postTokenEndpoint(region, {
        grant_type: "refresh_token",
        refresh_token: refreshToken,
        client_id: getOauthClientIdFromRegion(region),
      });
      return { success: true, data };
    } catch (error) {
      return {
        success: false,
        error: messageOf(error),
        errorCode: classifyError(error),
      };
    }
  }

  cancelFlow(): CancelFlowOutput {
    if (!this.pendingFlow) {
      return { success: false, error: "No pending flow" };
    }
    this.pendingFlow.cancel("Authentication canceled");
    return { success: true };
  }

  private async runFlow(
    region: CloudRegion,
    kind: "login" | "signup",
  ): Promise<StartFlowOutput> {
    this.pendingFlow?.cancel("Superseded by a new sign-in attempt");
    try {
      const codeVerifier = randomBase64Url(32);
      const state = randomBase64Url(16);
      const authUrl = await this.buildAuthorizeUrl(region, codeVerifier, state);
      const target =
        kind === "signup" ? buildSignupUrl(region, authUrl) : authUrl;

      // Open before any network round-trip so the click's transient activation
      // still permits the popup. The window name is unique per flow: a fixed
      // name lets a concurrent sign-in in another tab reuse (and navigate away)
      // this flow's popup, stranding it until the timeout — its own callback
      // never fires and the shared channel only carries the other flow's state.
      const popup = window.open(
        target.toString(),
        `posthog-code-oauth-${state}`,
        POPUP_FEATURES,
      );
      if (!popup) {
        return {
          success: false,
          error:
            "The sign-in popup was blocked. Allow popups for this site and try again.",
        };
      }

      this.log.info("Waiting for OAuth callback", { region, kind });
      const code = await this.waitForCallback(state, popup);
      const data = await this.postTokenEndpoint(region, {
        grant_type: "authorization_code",
        code,
        redirect_uri: getWebRedirectUri(),
        client_id: getOauthClientIdFromRegion(region),
        code_verifier: codeVerifier,
      });
      return { success: true, data };
    } catch (error) {
      this.log.warn("Web OAuth flow failed", { error: messageOf(error) });
      return {
        success: false,
        error: messageOf(error),
        errorCode: classifyError(error),
      };
    }
  }

  private waitForCallback(
    expectedState: string,
    popup: Window,
  ): Promise<string> {
    return new Promise<string>((resolve, reject) => {
      const channel = new BroadcastChannel(OAUTH_CALLBACK_CHANNEL);
      const closePoll = window.setInterval(() => {
        if (popup.closed) {
          fail(new Error("The sign-in window was closed before completing"));
        }
      }, 1_000);
      const timeout = window.setTimeout(() => {
        fail(new Error("Authorization timed out"));
      }, FLOW_TIMEOUT_MS);

      const cleanup = () => {
        window.clearInterval(closePoll);
        window.clearTimeout(timeout);
        channel.close();
        this.pendingFlow = null;
      };
      const fail = (error: Error) => {
        cleanup();
        if (!popup.closed) popup.close();
        reject(error);
      };
      this.pendingFlow = { cancel: (reason) => fail(new Error(reason)) };

      channel.onmessage = (event: MessageEvent<OAuthCallbackMessage>) => {
        const { code, state, error } = event.data ?? {};
        if (state !== expectedState) {
          this.log.warn("Ignoring OAuth callback with mismatched state");
          return;
        }
        if (error) {
          fail(new Error(`Authorization failed: ${error}`));
          return;
        }
        if (!code) {
          fail(new Error("Authorization callback carried no code"));
          return;
        }
        cleanup();
        resolve(code);
      };
    });
  }

  private async buildAuthorizeUrl(
    region: CloudRegion,
    codeVerifier: string,
    state: string,
  ): Promise<URL> {
    const codeChallenge = await sha256Base64Url(codeVerifier);
    const url = new URL(`${getCloudUrlFromRegion(region)}/oauth/authorize`);
    url.searchParams.set("client_id", getOauthClientIdFromRegion(region));
    url.searchParams.set("redirect_uri", getWebRedirectUri());
    url.searchParams.set("response_type", "code");
    url.searchParams.set("code_challenge", codeChallenge);
    url.searchParams.set("code_challenge_method", "S256");
    url.searchParams.set("scope", OAUTH_SCOPES.join(" "));
    url.searchParams.set("required_access_level", "project");
    url.searchParams.set("state", state);
    return url;
  }

  private async postTokenEndpoint(
    region: CloudRegion,
    body: Record<string, string>,
  ): Promise<OAuthTokenResponse> {
    const response = await fetch(
      `${getCloudUrlFromRegion(region)}/oauth/token`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(TOKEN_FETCH_TIMEOUT_MS),
      },
    );
    if (!response.ok) {
      throw new HttpError(
        response.status,
        `Token request failed: ${response.status} ${response.statusText}`,
      );
    }
    return oAuthTokenResponse.parse(await response.json());
  }
}

/**
 * Runs on the popup when the OAuth server redirects it to /oauth/callback:
 * relays the result to the opener tab and closes itself. main.tsx routes here
 * instead of rendering the app.
 */
export function completeOAuthCallbackPage(): void {
  const params = new URL(window.location.href).searchParams;
  const message: OAuthCallbackMessage = {
    code: params.get("code"),
    state: params.get("state"),
    error: params.get("error"),
  };
  const channel = new BroadcastChannel(OAUTH_CALLBACK_CHANNEL);
  channel.postMessage(message);
  channel.close();

  // Drop the one-time code from the URL/history before showing anything.
  window.history.replaceState(null, "", OAUTH_CALLBACK_PATH);
  const root = document.getElementById("root");
  if (root) {
    root.textContent = message.error
      ? `Sign-in failed: ${message.error}`
      : "Signed in — you can close this window.";
  }
  window.close();
}

function buildSignupUrl(region: CloudRegion, authUrl: URL): URL {
  const signupUrl = new URL(`${getCloudUrlFromRegion(region)}/signup`);
  signupUrl.searchParams.set("next", `${authUrl.pathname}${authUrl.search}`);
  return signupUrl;
}

function randomBase64Url(byteLength: number): string {
  const bytes = crypto.getRandomValues(new Uint8Array(byteLength));
  return base64UrlEncode(bytes);
}

async function sha256Base64Url(input: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(input),
  );
  return base64UrlEncode(new Uint8Array(digest));
}

function base64UrlEncode(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary)
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replace(/=+$/, "");
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function classifyError(error: unknown): OAuthErrorCode {
  if (error instanceof HttpError) {
    if (error.status >= 500) return "server_error";
    if (error.status === 401 || error.status === 403) return "auth_error";
    return "unknown_error";
  }
  // fetch rejects with TypeError on network/CORS failure; AbortSignal.timeout
  // rejects with a DOMException named TimeoutError.
  if (error instanceof TypeError) return "network_error";
  if (error instanceof DOMException && error.name === "TimeoutError") {
    return "network_error";
  }
  return "unknown_error";
}
