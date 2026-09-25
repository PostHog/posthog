import { fetch } from "expo/fetch";
import { requireSession, useAuth } from "@/lib/auth";

export type FetchInit = NonNullable<Parameters<typeof fetch>[1]>;

export function getBaseUrl(): string {
  return requireSession().host;
}

let pendingRefresh: Promise<string> | null = null;

// One refresh at a time, so parallel 401s do not race each other's tokens.
export function refreshAccessTokenOnce(): Promise<string> {
  if (!pendingRefresh) {
    pendingRefresh = useAuth
      .getState()
      .refresh()
      .finally(() => {
        pendingRefresh = null;
      });
  }
  return pendingRefresh;
}

export function getProjectId(): number {
  return requireSession().projectId;
}

export function getAccessToken(): string {
  return requireSession().apiKey;
}

// Hermes has no AbortSignal.timeout, so build one by hand.
export function createTimeoutSignal(ms: number): AbortSignal {
  const controller = new AbortController();
  setTimeout(() => controller.abort(), ms);
  return controller.signal;
}

function mergeHeaders(
  base: Record<string, string>,
  override: HeadersInit | undefined,
): Record<string, string> {
  const merged = { ...base };
  if (!override) return merged;
  if (override instanceof Headers) {
    override.forEach((value, key) => {
      merged[key] = value;
    });
  } else if (Array.isArray(override)) {
    for (const [key, value] of override) merged[key] = value;
  } else {
    Object.assign(merged, override);
  }
  return merged;
}

export async function authedFetch(
  url: string,
  init?: FetchInit,
): Promise<Response> {
  const headers = mergeHeaders(
    {
      Authorization: `Bearer ${getAccessToken()}`,
      "Content-Type": "application/json",
      "User-Agent": "posthog/mobilehog; version: 0.1.0",
    },
    init?.headers as HeadersInit | undefined,
  );
  // The login session cookie must not ride along, or Django takes the session
  // path and rejects the POST for a missing CSRF token.
  const response = await fetch(url, { ...init, headers, credentials: "omit" });
  if (response.status !== 401 || !requireSession().refreshToken) {
    return response;
  }
  const token = await refreshAccessTokenOnce();
  return fetch(url, {
    ...init,
    headers: { ...headers, Authorization: `Bearer ${token}` },
    credentials: "omit",
  });
}
