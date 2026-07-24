import * as AuthSession from "expo-auth-session";
import * as WebBrowser from "expo-web-browser";
import type { CloudRegion, OAuthConfig, OAuthTokenResponse } from "../types";
import { getCloudUrlFromRegion, getOauthClientIdFromRegion } from "./constants";

// Required for web browser auth session to work properly
WebBrowser.maybeCompleteAuthSession();

export function getRedirectUri(): string {
  return AuthSession.makeRedirectUri({
    scheme: "posthog",
    path: "callback",
  });
}

export function getAuthorizationEndpoint(region: CloudRegion): string {
  return `${getCloudUrlFromRegion(region)}/oauth/authorize`;
}

export function getTokenEndpoint(region: CloudRegion): string {
  return `${getCloudUrlFromRegion(region)}/oauth/token`;
}

export async function exchangeCodeForToken(
  code: string,
  codeVerifier: string,
  config: OAuthConfig,
): Promise<OAuthTokenResponse> {
  const cloudUrl = getCloudUrlFromRegion(config.cloudRegion);
  const redirectUri = getRedirectUri();

  const response = await fetch(`${cloudUrl}/oauth/token`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      grant_type: "authorization_code",
      code,
      redirect_uri: redirectUri,
      client_id: getOauthClientIdFromRegion(config.cloudRegion),
      code_verifier: codeVerifier,
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(
      `Token exchange failed: ${response.statusText} - ${errorText}`,
    );
  }

  return response.json();
}

export type OAuthRefreshErrorCode =
  | "auth_error"
  | "server_error"
  | "network_error"
  | "unknown_error";

export class TokenRefreshError extends Error {
  readonly errorCode: OAuthRefreshErrorCode;

  constructor(errorCode: OAuthRefreshErrorCode, message: string) {
    super(message);
    this.name = "TokenRefreshError";
    this.errorCode = errorCode;
  }
}

async function parseOAuthErrorCode(response: Response): Promise<string | null> {
  try {
    const body = (await response.json()) as { error?: unknown };
    return typeof body.error === "string" ? body.error : null;
  } catch {
    return null;
  }
}

export async function refreshAccessToken(
  refreshToken: string,
  region: CloudRegion,
): Promise<OAuthTokenResponse> {
  const cloudUrl = getCloudUrlFromRegion(region);

  let response: Response;
  try {
    response = await fetch(`${cloudUrl}/oauth/token`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        grant_type: "refresh_token",
        refresh_token: refreshToken,
        client_id: getOauthClientIdFromRegion(region),
      }),
    });
  } catch (error) {
    throw new TokenRefreshError(
      "network_error",
      error instanceof Error ? error.message : "Token refresh network error",
    );
  }

  if (!response.ok) {
    // 401/403 are always auth failures. A 400 only means a dead refresh token
    // when the OAuth error is invalid_grant/invalid_token; other 400s like
    // invalid_client are config bugs that must not sign the user out, or they
    // could never log back in with the same broken config.
    const oauthErrorCode =
      response.status === 400 ? await parseOAuthErrorCode(response) : null;
    const isAuthError =
      response.status === 401 ||
      response.status === 403 ||
      oauthErrorCode === "invalid_grant" ||
      oauthErrorCode === "invalid_token";
    const errorCode: OAuthRefreshErrorCode = isAuthError
      ? "auth_error"
      : response.status >= 500
        ? "server_error"
        : "unknown_error";
    throw new TokenRefreshError(
      errorCode,
      `Token refresh failed: ${response.status} ${response.statusText}`,
    );
  }

  return response.json();
}

export interface OAuthFlowResult {
  success: boolean;
  data?: OAuthTokenResponse;
  error?: string;
}

export async function performOAuthFlow(
  config: OAuthConfig,
): Promise<OAuthFlowResult> {
  try {
    const redirectUri = getRedirectUri();
    const clientId = getOauthClientIdFromRegion(config.cloudRegion);

    const discovery: AuthSession.DiscoveryDocument = {
      authorizationEndpoint: getAuthorizationEndpoint(config.cloudRegion),
      tokenEndpoint: getTokenEndpoint(config.cloudRegion),
    };

    // Let expo-auth-session handle PKCE internally
    const authRequest = new AuthSession.AuthRequest({
      clientId,
      scopes: config.scopes,
      redirectUri,
      usePKCE: true,
      extraParams: {
        required_access_level: "project",
      },
    });

    // promptAsync will load the request internally and generate PKCE
    const authResult = await authRequest.promptAsync(discovery);

    if (authResult.type === "cancel" || authResult.type === "dismiss") {
      return {
        success: false,
        error: "Authorization cancelled",
      };
    }

    if (authResult.type === "error") {
      return {
        success: false,
        error: authResult.error?.message || "Authorization failed",
      };
    }

    if (authResult.type !== "success" || !authResult.params.code) {
      return {
        success: false,
        error: "No authorization code received",
      };
    }

    // Use the AuthRequest's codeVerifier for token exchange
    if (!authRequest.codeVerifier) {
      return {
        success: false,
        error: "PKCE code verifier not available",
      };
    }

    const tokenResponse = await exchangeCodeForToken(
      authResult.params.code,
      authRequest.codeVerifier,
      config,
    );

    return {
      success: true,
      data: tokenResponse,
    };
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? error.message : "Unknown error",
    };
  }
}
