import * as AuthSession from "expo-auth-session";
import * as WebBrowser from "expo-web-browser";

WebBrowser.maybeCompleteAuthSession();

export type CloudRegion = "us" | "eu";

// v1 mobile's public OAuth clients, registered for the posthog://callback scheme.
const CLIENT_IDS: Record<CloudRegion, string> = {
  us: "a5TY7w9IjFYfes6dkPgZe6envclWw3bm2UD8ZTlm",
  eu: "1A7vO138Fh5sYmJislicN4F5HnttI6urmFttxPDU",
};

export const CLOUD_HOSTS: Record<CloudRegion, string> = {
  us: "https://us.posthog.com",
  eu: "https://eu.posthog.com",
};

const SCOPES = [
  "user:read",
  "user:write",
  "project:read",
  "organization:read",
  "organization:write",
  "task:write",
  "integration:read",
  "conversation:write",
  "query:read",
  "llm_skill:read",
];

export interface OAuthTokens {
  access_token: string;
  expires_in: number;
  refresh_token: string;
  scoped_teams?: number[];
}

function redirectUri(): string {
  return AuthSession.makeRedirectUri({ scheme: "posthog", path: "callback" });
}

async function tokenRequest(
  region: CloudRegion,
  body: Record<string, string>,
): Promise<OAuthTokens> {
  const response = await fetch(`${CLOUD_HOSTS[region]}/oauth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, client_id: CLIENT_IDS[region] }),
  });
  if (!response.ok) {
    throw new Error(
      `Token request failed (${response.status}): ${await response.text()}`,
    );
  }
  return (await response.json()) as OAuthTokens;
}

// With `signup`, the browser opens account creation first and lands on the
// authorize page afterwards, so a new user ends up signed in to the app.
export async function signInWithOAuth(
  region: CloudRegion,
  signup = false,
): Promise<OAuthTokens> {
  const host = CLOUD_HOSTS[region];
  const request = new AuthSession.AuthRequest({
    clientId: CLIENT_IDS[region],
    scopes: SCOPES,
    redirectUri: redirectUri(),
    usePKCE: true,
    extraParams: { required_access_level: "project" },
  });
  const discovery = { authorizationEndpoint: `${host}/oauth/authorize` };
  const authUrl = await request.makeAuthUrlAsync(discovery);
  const next = encodeURIComponent(authUrl.slice(host.length));
  const result = await request.promptAsync(discovery, {
    url: signup ? `${host}/signup?next=${next}` : authUrl,
  });
  if (result.type !== "success" || !result.params.code) {
    throw new Error(
      result.type === "error"
        ? (result.error?.message ?? "Authorization failed")
        : "Sign in was cancelled",
    );
  }
  if (!request.codeVerifier) throw new Error("PKCE verifier missing");
  return tokenRequest(region, {
    grant_type: "authorization_code",
    code: result.params.code,
    redirect_uri: redirectUri(),
    code_verifier: request.codeVerifier,
  });
}

export function refreshOAuth(
  region: CloudRegion,
  refreshToken: string,
): Promise<OAuthTokens> {
  return tokenRequest(region, {
    grant_type: "refresh_token",
    refresh_token: refreshToken,
  });
}
