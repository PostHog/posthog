import { spawn } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { createServer } from "node:http";
import type {
  OAuthCredentials,
  OAuthLoginCallbacks,
} from "@earendil-works/pi-ai";
import {
  type CloudRegion,
  getCloudUrlFromRegion,
  getOauthClientIdFromRegion,
  OAUTH_SCOPES,
} from "@posthog/shared";

const OAUTH_TIMEOUT_MS = 180_000;
const TOKEN_FETCH_TIMEOUT_MS = 30_000;
const TOKEN_EXPIRY_SKEW_MS = 60_000;
const DEFAULT_CALLBACK_PORT = 8237;
const CALLBACK_PATH = "/callback";

interface OAuthTokenResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  token_type: string;
  scope?: string;
}

export function getCallbackPort(): number {
  const raw = process.env.HARNESS_OAUTH_PORT;
  const parsed = raw ? Number.parseInt(raw, 10) : Number.NaN;
  return Number.isInteger(parsed) && parsed > 0
    ? parsed
    : DEFAULT_CALLBACK_PORT;
}

export function getRedirectUri(port: number = getCallbackPort()): string {
  return `http://localhost:${port}${CALLBACK_PATH}`;
}

function generateCodeVerifier(): string {
  return randomBytes(32).toString("base64url");
}

function generateCodeChallenge(verifier: string): string {
  return createHash("sha256").update(verifier).digest("base64url");
}

export function buildAuthorizeUrl(
  region: CloudRegion,
  codeChallenge: string,
  redirectUri: string,
): URL {
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

function toCredentials(
  response: OAuthTokenResponse,
  region: CloudRegion,
): OAuthCredentials {
  return {
    access: response.access_token,
    refresh: response.refresh_token,
    expires: Date.now() + response.expires_in * 1000 - TOKEN_EXPIRY_SKEW_MS,
    region,
  };
}

async function postToken(
  region: CloudRegion,
  body: Record<string, string>,
): Promise<OAuthTokenResponse> {
  const cloudUrl = getCloudUrlFromRegion(region);
  const response = await fetch(`${cloudUrl}/oauth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(TOKEN_FETCH_TIMEOUT_MS),
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(
      `PostHog token request failed: ${response.status} ${response.statusText} ${detail}`.trim(),
    );
  }
  return (await response.json()) as OAuthTokenResponse;
}

function openBrowser(url: string): void {
  const platform = process.platform;
  const command =
    platform === "darwin" ? "open" : platform === "win32" ? "cmd" : "xdg-open";
  const args = platform === "win32" ? ["/c", "start", "", url] : [url];
  try {
    spawn(command, args, { stdio: "ignore", detached: true }).unref();
  } catch {}
}

const SUCCESS_PAGE = `<!doctype html><html><head><meta charset="utf-8"><title>PostHog</title></head><body style="font-family:system-ui;text-align:center;padding-top:20vh"><h1>Authentication complete</h1><p>You can close this window and return to your terminal.</p></body></html>`;
const ERROR_PAGE = `<!doctype html><html><head><meta charset="utf-8"><title>PostHog</title></head><body style="font-family:system-ui;text-align:center;padding-top:20vh"><h1>Authentication failed</h1><p>Please return to your terminal and try again.</p></body></html>`;

function waitForCallbackCode(options: {
  port: number;
  expectedState: string;
  signal?: AbortSignal;
  onListening: () => void;
}): Promise<string> {
  const { port, expectedState, signal, onListening } = options;
  return new Promise<string>((resolve, reject) => {
    const server = createServer((req, res) => {
      const url = new URL(req.url ?? "", `http://localhost:${port}`);
      if (url.pathname !== CALLBACK_PATH) {
        res.writeHead(404);
        res.end();
        return;
      }
      const code = url.searchParams.get("code");
      const state = url.searchParams.get("state");
      const error = url.searchParams.get("error");
      // Determine success/failure before responding, so the browser never
      // shows "Authentication complete" on a path we're about to reject (an
      // OAuth error, a missing code, or a state mismatch).
      const failureReason = error
        ? `PostHog OAuth error: ${error}`
        : !code
          ? "PostHog OAuth callback missing code"
          : expectedState && state !== expectedState
            ? "PostHog OAuth state mismatch"
            : undefined;
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(failureReason ? ERROR_PAGE : SUCCESS_PAGE);
      cleanup();
      if (failureReason) {
        reject(new Error(failureReason));
      } else {
        // `code` is guaranteed non-null here: `failureReason` covers the `!code` case above.
        resolve(code as string);
      }
    });

    const timeout = setTimeout(() => {
      cleanup();
      reject(new Error("PostHog OAuth timed out"));
    }, OAUTH_TIMEOUT_MS);

    const onAbort = () => {
      cleanup();
      reject(new Error("PostHog OAuth cancelled"));
    };

    function cleanup(): void {
      clearTimeout(timeout);
      signal?.removeEventListener("abort", onAbort);
      server.close();
    }

    if (signal?.aborted) {
      onAbort();
      return;
    }
    signal?.addEventListener("abort", onAbort);

    server.on("error", (err) => {
      cleanup();
      reject(err);
    });
    server.listen(port, "127.0.0.1", onListening);
  });
}

const REGION_LOGIN_OPTIONS: { id: CloudRegion; label: string }[] = [
  { id: "us", label: "United States" },
  { id: "eu", label: "European Union" },
];

/**
 * Prompts the user to pick their PostHog region via the login callbacks'
 * selector. `dev` is intentionally not offered here; it stays reachable only
 * through an explicit `POSTHOG_REGION=dev`.
 */
async function selectRegion(
  callbacks: OAuthLoginCallbacks,
): Promise<CloudRegion> {
  const picked = await callbacks.onSelect({
    message: "Select your PostHog region",
    options: REGION_LOGIN_OPTIONS,
  });
  if (picked !== "us" && picked !== "eu") {
    throw new Error("PostHog region selection cancelled");
  }
  return picked;
}

/**
 * Logs in to PostHog. When `explicitRegion` is provided (an explicit option
 * or `POSTHOG_REGION`), that region is used directly; otherwise the user is
 * prompted to choose between the supported regions.
 */
export async function loginPosthog(
  callbacks: OAuthLoginCallbacks,
  explicitRegion?: CloudRegion,
): Promise<OAuthCredentials> {
  const region = explicitRegion ?? (await selectRegion(callbacks));
  const port = getCallbackPort();
  const redirectUri = getRedirectUri(port);
  const codeVerifier = generateCodeVerifier();
  const codeChallenge = generateCodeChallenge(codeVerifier);
  const state = randomBytes(16).toString("base64url");

  const authUrl = buildAuthorizeUrl(region, codeChallenge, redirectUri);
  authUrl.searchParams.set("state", state);
  const authUrlString = authUrl.toString();

  const code = await waitForCallbackCode({
    port,
    expectedState: state,
    signal: callbacks.signal,
    onListening: () => {
      callbacks.onAuth({
        url: authUrlString,
        instructions:
          "Opening your browser to sign in to PostHog. If it doesn't open, visit the URL above.",
      });
      openBrowser(authUrlString);
    },
  });

  const tokens = await postToken(region, {
    grant_type: "authorization_code",
    code,
    redirect_uri: redirectUri,
    client_id: getOauthClientIdFromRegion(region),
    code_verifier: codeVerifier,
  });

  return toCredentials(tokens, region);
}

export async function refreshPosthog(
  region: CloudRegion,
  credentials: OAuthCredentials,
): Promise<OAuthCredentials> {
  const effectiveRegion =
    (credentials.region as CloudRegion | undefined) ?? region;
  const tokens = await postToken(effectiveRegion, {
    grant_type: "refresh_token",
    refresh_token: credentials.refresh,
    client_id: getOauthClientIdFromRegion(effectiveRegion),
  });
  return toCredentials(tokens, effectiveRegion);
}
