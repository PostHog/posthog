import { fetch } from "expo/fetch";
import Constants from "expo-constants";
import { useAuthStore } from "@/features/auth";
import { logger } from "@/lib/logger";

// Derive the init shape directly from expo/fetch so we don't import from
// expo's internal build output (which can move between versions).
type FetchInit = NonNullable<Parameters<typeof fetch>[1]>;

const log = logger.scope("api");

const USER_AGENT = `posthog/mobile.hog.dev; version: ${Constants.expoConfig?.version ?? "unknown"}`;

export function getHeaders(): Record<string, string> {
  const { oauthAccessToken } = useAuthStore.getState();
  if (!oauthAccessToken) {
    throw new Error("Not authenticated");
  }
  return {
    Authorization: `Bearer ${oauthAccessToken}`,
    "Content-Type": "application/json",
    "User-Agent": USER_AGENT,
  };
}

export function getAccessToken(): string {
  const { oauthAccessToken } = useAuthStore.getState();
  if (!oauthAccessToken) {
    throw new Error("Not authenticated");
  }
  return oauthAccessToken;
}

export function getBaseUrl(): string {
  const { cloudRegion, getCloudUrlFromRegion } = useAuthStore.getState();
  if (!cloudRegion) {
    throw new Error("No cloud region set");
  }
  return getCloudUrlFromRegion(cloudRegion);
}

export function getProjectId(): number {
  const { projectId } = useAuthStore.getState();
  if (!projectId) {
    throw new Error("No project ID set");
  }
  return projectId;
}

/**
 * Returns an `AbortSignal` that aborts after `ms` milliseconds.
 *
 * Replaces `AbortSignal.timeout(ms)`, which is unimplemented in the Hermes
 * runtime that React Native uses — calling it throws
 * `TypeError: AbortSignal.timeout is not a function`. Use this helper for any
 * fetch that needs a request timeout on mobile.
 */
export function createTimeoutSignal(ms: number): AbortSignal {
  const controller = new AbortController();
  setTimeout(() => controller.abort(), ms);
  return controller.signal;
}

// Concurrent 401s would otherwise stampede the refresh endpoint and have the
// in-flight responses invalidate each other's new tokens. Share a single
// pending refresh across all callers and reset it once it settles.
let pendingRefresh: Promise<void> | null = null;

async function refreshAccessTokenOnce(): Promise<void> {
  if (pendingRefresh) return pendingRefresh;
  const promise = useAuthStore
    .getState()
    .refreshAccessToken()
    .finally(() => {
      if (pendingRefresh === promise) {
        pendingRefresh = null;
      }
    });
  pendingRefresh = promise;
  return promise;
}

async function isAuthFailureResponse(response: Response): Promise<boolean> {
  if (response.status === 401) return true;
  if (response.status !== 403) return false;
  try {
    const body = await response.clone().json();
    return (
      body?.code === "authentication_failed" ||
      body?.type === "authentication_error"
    );
  } catch {
    return false;
  }
}

function mergeHeaders(
  base: Record<string, string>,
  override: HeadersInit | undefined,
): Record<string, string> {
  if (!override) return base;
  const merged: Record<string, string> = { ...base };
  if (override instanceof Headers) {
    override.forEach((value, key) => {
      merged[key] = value;
    });
    return merged;
  }
  if (Array.isArray(override)) {
    for (const [key, value] of override) {
      merged[key] = value;
    }
    return merged;
  }
  for (const [key, value] of Object.entries(override)) {
    merged[key] = value;
  }
  return merged;
}

/**
 * `fetch` against the PostHog API with automatic token refresh on auth
 * failure. On a 401 — or a 403 whose JSON body looks like an authentication
 * failure (`code: "authentication_failed"` / `type: "authentication_error"`) —
 * triggers a single shared token refresh and retries the request once. If the
 * refresh itself fails, the original response is returned so callers fall
 * through to their existing error-handling and sign-out flows.
 *
 * Mirrors the desktop fetcher's retry semantics
 * (apps/code/src/renderer/api/fetcher.ts).
 */
export async function authedFetch(
  url: string,
  init: FetchInit = {},
): Promise<Response> {
  const headers = mergeHeaders(getHeaders(), init.headers);
  let response: Response = await fetch(url, { ...init, headers });

  if (response.ok || !(await isAuthFailureResponse(response))) {
    return response;
  }

  try {
    await refreshAccessTokenOnce();
  } catch (err) {
    log.warn("Token refresh on auth failure failed", {
      url,
      status: response.status,
      error: err instanceof Error ? err.message : String(err),
    });
    return response;
  }

  const retryHeaders = mergeHeaders(getHeaders(), init.headers);
  response = await fetch(url, { ...init, headers: retryHeaders });
  return response;
}

export async function registerPushToken(args: {
  token: string;
  platform: string;
}): Promise<void> {
  const baseUrl = getBaseUrl();

  // Push tokens are per-user, not per-project — endpoint lives under
  // /api/users/@me/ alongside the other user-scoped APIs.
  const url = `${baseUrl}/api/users/@me/push_tokens/`;
  const response = await authedFetch(url, {
    method: "POST",
    body: JSON.stringify(args),
  });

  if (!response.ok) {
    const body = await response.text().catch(() => "");
    log.warn("registerPushToken failed", {
      url,
      status: response.status,
      statusText: response.statusText,
      body: body.slice(0, 500),
    });
    throw new Error(
      `registerPushToken failed: ${response.status} ${response.statusText} — ${body.slice(0, 200)}`,
    );
  }
}

export async function deletePushToken(args: { token: string }): Promise<void> {
  const baseUrl = getBaseUrl();

  // Unregister is a POST sub-action (not DELETE) because some clients and
  // proxies strip request bodies on DELETE.
  const response = await authedFetch(
    `${baseUrl}/api/users/@me/push_tokens/unregister/`,
    {
      method: "POST",
      body: JSON.stringify(args),
    },
  );

  if (!response.ok) {
    log.debug("deletePushToken non-OK response", {
      status: response.status,
    });
  }
}
