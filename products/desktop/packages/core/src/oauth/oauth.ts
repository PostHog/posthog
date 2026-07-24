import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import { CRYPTO_SERVICE, type ICrypto } from "@posthog/platform/crypto";
import {
  DEEP_LINK_SERVICE,
  type IDeepLinkRegistry,
} from "@posthog/platform/deep-link";
import {
  type IMainWindow,
  MAIN_WINDOW_SERVICE,
} from "@posthog/platform/main-window";
import {
  type IUrlLauncher,
  URL_LAUNCHER_SERVICE,
} from "@posthog/platform/url-launcher";
import {
  type BackoffOptions,
  getCloudUrlFromRegion,
  getOauthClientIdFromRegion,
  OAUTH_SCOPES,
  sleepWithBackoff,
} from "@posthog/shared";
import { inject, injectable } from "inversify";
import { OAUTH_HOST, type OAuthHost } from "./identifiers";
import type {
  CancelFlowOutput,
  CloudRegion,
  OAuthTokenResponse,
  RefreshTokenOutput,
  StartFlowOutput,
} from "./schemas";

const OAUTH_TIMEOUT_MS = 180_000; // 3 minutes
const TOKEN_FETCH_TIMEOUT_MS = 30_000;
const DEV_CALLBACK_PORT = 8237;

const NETWORK_ERROR_MESSAGE =
  "Could not connect to PostHog. Please check your internet connection and try again.";

const TOKEN_FETCH_MAX_ATTEMPTS = 3;
const TOKEN_FETCH_BACKOFF: BackoffOptions = {
  initialDelayMs: 1_000,
  maxDelayMs: 5_000,
  multiplier: 2,
};

interface OAuthConfig {
  scopes: string[];
  cloudRegion: CloudRegion;
}

interface PendingOAuthFlow {
  codeVerifier: string;
  config: OAuthConfig;
  resolve: (code: string) => void;
  reject: (error: Error) => void;
  timeoutId?: NodeJS.Timeout;
  abortController?: AbortController;
}

async function parseOAuthErrorCode(response: Response): Promise<string | null> {
  try {
    const body = (await response.json()) as { error?: unknown };
    return typeof body.error === "string" ? body.error : null;
  } catch {
    return null;
  }
}

@injectable()
export class OAuthService {
  private pendingFlow: PendingOAuthFlow | null = null;
  private readonly log: ScopedLogger;

  constructor(
    @inject(DEEP_LINK_SERVICE)
    private readonly deepLinkService: IDeepLinkRegistry,
    @inject(URL_LAUNCHER_SERVICE)
    private readonly urlLauncher: IUrlLauncher,
    @inject(MAIN_WINDOW_SERVICE)
    private readonly mainWindow: IMainWindow,
    @inject(OAUTH_HOST)
    private readonly host: OAuthHost,
    @inject(ROOT_LOGGER)
    logger: RootLogger,
    @inject(CRYPTO_SERVICE)
    private readonly crypto: ICrypto,
  ) {
    this.log = logger.scope("oauth-service");
    // Register OAuth callback handler for deep links
    this.deepLinkService.registerHandler("callback", (_path, searchParams) =>
      this.handleOAuthCallback(searchParams),
    );
  }

  private handleOAuthCallback(searchParams: URLSearchParams): boolean {
    const code = searchParams.get("code");
    const error = searchParams.get("error");

    if (!this.pendingFlow) {
      // Same deep link as desktop sign-in (`posthog-code://callback`), but auth finished in
      // the browser (e.g. GitHub on PostHog Cloud) — refocus so the user lands back in Code.
      this.log.info(
        "OAuth callback deep link with no in-app flow — refocusing (e.g. return from web auth)",
      );
      this.log.info(
        "oauth callback deep link (no in-app flow) — focusing window",
      );
      if (this.mainWindow.isMinimized()) this.mainWindow.restore();
      this.mainWindow.focus();
      return true;
    }

    const { resolve, reject, timeoutId } = this.pendingFlow;
    clearTimeout(timeoutId);
    this.pendingFlow = null;

    if (error) {
      reject(new Error(`OAuth error: ${error}`));
      return true;
    }

    if (code) {
      resolve(code);
      return true;
    }

    reject(new Error("OAuth callback missing code"));
    return true;
  }

  /**
   * Get the redirect URI based on environment.
   */
  private getRedirectUri(): string {
    return this.host.isDev
      ? `http://localhost:${DEV_CALLBACK_PORT}/callback`
      : `${this.deepLinkService.getProtocol()}://callback`;
  }

  /**
   * Start the OAuth flow.
   * Uses HTTP callback in development, deep links in production.
   */
  public async startFlow(region: CloudRegion): Promise<StartFlowOutput> {
    try {
      // Cancel any existing flow
      this.cancelFlow();

      const config: OAuthConfig = {
        scopes: OAUTH_SCOPES,
        cloudRegion: region,
      };

      const codeVerifier = this.generateCodeVerifier();
      const authUrl = this.buildAuthorizeUrl(region, codeVerifier);

      return await this.startFlowWithUrl(
        config,
        codeVerifier,
        authUrl.toString(),
      );
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : "Unknown error",
      };
    }
  }

  /**
   * Start the OAuth flow from the signup page.
   */
  public async startSignupFlow(region: CloudRegion): Promise<StartFlowOutput> {
    try {
      // Cancel any existing flow
      this.cancelFlow();

      const config: OAuthConfig = {
        scopes: OAUTH_SCOPES,
        cloudRegion: region,
      };

      const codeVerifier = this.generateCodeVerifier();
      const authUrl = this.buildAuthorizeUrl(region, codeVerifier);
      const signupUrl = this.buildSignupUrl(region, authUrl);

      return await this.startFlowWithUrl(
        config,
        codeVerifier,
        signupUrl.toString(),
      );
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : "Unknown error",
      };
    }
  }

  /**
   * Refresh an access token using a refresh token.
   */
  public async refreshToken(
    refreshToken: string,
    region: CloudRegion,
  ): Promise<RefreshTokenOutput> {
    try {
      const cloudUrl = getCloudUrlFromRegion(region);

      const response = await fetch(`${cloudUrl}/oauth/token`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          grant_type: "refresh_token",
          refresh_token: refreshToken,
          client_id: getOauthClientIdFromRegion(region),
        }),
        signal: AbortSignal.timeout(TOKEN_FETCH_TIMEOUT_MS),
      });

      if (!response.ok) {
        // 401/403 are always auth failures. A 400 is only a dead refresh token
        // when the OAuth error is invalid_grant/invalid_token; other 400s like
        // invalid_client or invalid_request are config bugs and must not log the
        // user out, or they would be unable to log back in with the same broken
        // config.
        const oauthErrorCode =
          response.status === 400 ? await parseOAuthErrorCode(response) : null;
        const isAuthError =
          response.status === 401 ||
          response.status === 403 ||
          oauthErrorCode === "invalid_grant" ||
          oauthErrorCode === "invalid_token";
        // 5xx are server errors - should be retried
        const isServerError = response.status >= 500;
        this.log.warn(
          `Token refresh failed: ${response.status} ${response.statusText}`,
        );
        return {
          success: false,
          error: `Token refresh failed: ${response.status} ${response.statusText}`,
          errorCode: isAuthError
            ? "auth_error"
            : isServerError
              ? "server_error"
              : "unknown_error",
        };
      }

      const tokenResponse = (await response.json()) as OAuthTokenResponse;

      return {
        success: true,
        data: tokenResponse,
      };
    } catch {
      return {
        success: false,
        error: NETWORK_ERROR_MESSAGE,
        errorCode: "network_error",
      };
    }
  }

  /**
   * Cancel any pending OAuth flow.
   */
  public cancelFlow(): CancelFlowOutput {
    try {
      if (this.pendingFlow) {
        if (this.pendingFlow.abortController) {
          // Dev HTTP-callback path: stop the workspace-server callback server.
          this.pendingFlow.abortController.abort();
          this.pendingFlow = null;
        } else {
          if (this.pendingFlow.timeoutId) {
            clearTimeout(this.pendingFlow.timeoutId);
          }
          this.pendingFlow.reject(new Error("OAuth flow cancelled"));
          this.pendingFlow = null;
        }
      }
      return { success: true };
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : "Unknown error",
      };
    }
  }

  /**
   * Wait for OAuth callback via deep link (production).
   */
  private async waitForDeepLinkCallback(
    codeVerifier: string,
    config: OAuthConfig,
    authUrl: string,
  ): Promise<string> {
    return new Promise<string>((resolve, reject) => {
      const timeoutId = setTimeout(() => {
        this.pendingFlow = null;
        reject(new Error("Authorization timed out"));
      }, OAUTH_TIMEOUT_MS);

      this.pendingFlow = {
        codeVerifier,
        config,
        resolve,
        reject,
        timeoutId,
      };

      // Open the browser for authentication
      this.urlLauncher.launch(authUrl).catch((error) => {
        clearTimeout(timeoutId);
        this.pendingFlow = null;
        reject(new Error(`Failed to open browser: ${error.message}`));
      });
    });
  }

  /**
   * Wait for OAuth callback via the workspace-server HTTP server (development).
   */
  private async waitForHttpCallback(
    codeVerifier: string,
    config: OAuthConfig,
    authUrl: string,
  ): Promise<string> {
    const abortController = new AbortController();
    this.pendingFlow = {
      codeVerifier,
      config,
      resolve: () => {},
      reject: () => {},
      abortController,
    };

    try {
      return await this.host.waitForCode({
        port: DEV_CALLBACK_PORT,
        timeoutMs: OAUTH_TIMEOUT_MS,
        signal: abortController.signal,
        onListening: () => {
          this.log.info(
            `Dev OAuth callback server listening on port ${DEV_CALLBACK_PORT}`,
          );
          this.urlLauncher.launch(authUrl).catch(() => {
            abortController.abort();
          });
        },
      });
    } finally {
      this.pendingFlow = null;
    }
  }

  private async exchangeCodeForToken(
    code: string,
    codeVerifier: string,
    config: OAuthConfig,
  ): Promise<OAuthTokenResponse> {
    const cloudUrl = getCloudUrlFromRegion(config.cloudRegion);
    const redirectUri = this.getRedirectUri();
    const body = JSON.stringify({
      grant_type: "authorization_code",
      code,
      redirect_uri: redirectUri,
      client_id: getOauthClientIdFromRegion(config.cloudRegion),
      code_verifier: codeVerifier,
    });

    let lastError = "Token exchange failed";

    for (let attempt = 0; attempt < TOKEN_FETCH_MAX_ATTEMPTS; attempt++) {
      let response: Response;
      try {
        response = await fetch(`${cloudUrl}/oauth/token`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
          signal: AbortSignal.timeout(TOKEN_FETCH_TIMEOUT_MS),
        });
      } catch (error) {
        // fetch threw — DNS/TLS/socket failure. The raw message ("Failed to fetch",
        // "fetch failed", "terminated", etc.) leaks to the UI as-is, so we replace
        // it with something users can act on.
        lastError = NETWORK_ERROR_MESSAGE;
        this.log.warn("Token exchange network error", {
          attempt,
          error: error instanceof Error ? error.message : String(error),
        });
        if (attempt === TOKEN_FETCH_MAX_ATTEMPTS - 1) break;
        await sleepWithBackoff(attempt, TOKEN_FETCH_BACKOFF);
        continue;
      }

      if (response.ok) {
        return (await response.json()) as OAuthTokenResponse;
      }

      lastError = `Token exchange failed: ${response.status} ${response.statusText}`;
      const isServerError = response.status >= 500;
      if (!isServerError) {
        throw new Error(lastError);
      }

      this.log.warn("Token exchange server error", {
        attempt,
        status: response.status,
      });
      if (attempt === TOKEN_FETCH_MAX_ATTEMPTS - 1) break;
      await sleepWithBackoff(attempt, TOKEN_FETCH_BACKOFF);
    }

    throw new Error(lastError);
  }

  private buildAuthorizeUrl(region: CloudRegion, codeVerifier: string): URL {
    const codeChallenge = this.generateCodeChallenge(codeVerifier);
    const redirectUri = this.getRedirectUri();
    const cloudUrl = getCloudUrlFromRegion(region);
    const authUrl = new URL(`${cloudUrl}/oauth/authorize`);
    authUrl.searchParams.set("client_id", getOauthClientIdFromRegion(region));
    authUrl.searchParams.set("redirect_uri", redirectUri);
    authUrl.searchParams.set("response_type", "code");
    authUrl.searchParams.set("code_challenge", codeChallenge);
    authUrl.searchParams.set("code_challenge_method", "S256");
    authUrl.searchParams.set("scope", OAUTH_SCOPES.join(" "));
    authUrl.searchParams.set("required_access_level", "project");
    return authUrl;
  }

  private buildSignupUrl(region: CloudRegion, authUrl: URL): URL {
    const cloudUrl = getCloudUrlFromRegion(region);
    const signupUrl = new URL(`${cloudUrl}/signup`);
    const nextPath = `${authUrl.pathname}${authUrl.search}`;
    signupUrl.searchParams.set("next", nextPath);
    return signupUrl;
  }

  private async startFlowWithUrl(
    config: OAuthConfig,
    codeVerifier: string,
    authUrl: string,
  ): Promise<StartFlowOutput> {
    const code = this.host.isDev
      ? await this.waitForHttpCallback(codeVerifier, config, authUrl)
      : await this.waitForDeepLinkCallback(codeVerifier, config, authUrl);

    const tokenResponse = await this.exchangeCodeForToken(
      code,
      codeVerifier,
      config,
    );

    return {
      success: true,
      data: tokenResponse,
    };
  }

  private generateCodeVerifier(): string {
    return this.crypto.randomBase64Url(32);
  }

  private generateCodeChallenge(verifier: string): string {
    return this.crypto.sha256Base64Url(verifier);
  }

  /**
   * Open an external URL in the default browser.
   */
  public async openExternalUrl(url: string): Promise<void> {
    await this.urlLauncher.launch(url);
  }
}
