import { fetch } from "expo/fetch";
import { POSTHOG_HOST } from "@/config";
import { requireSession } from "@/lib/auth";

export type FetchInit = NonNullable<Parameters<typeof fetch>[1]>;

export function getBaseUrl(): string {
  return POSTHOG_HOST;
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
  return fetch(url, { ...init, headers, credentials: "omit" });
}
