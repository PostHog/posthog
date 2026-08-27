import type { CloudRegion } from "./regions";
import { getCloudUrlFromRegion } from "./urls";

// Paired with frontend/src/lib/utils/crossSurfaceSessionId.ts in the PostHog
// monorepo, which reads and strips this param before posthog.init so both
// surfaces record under one session. Keep the param name in sync.
export const POSTHOG_SESSION_ID_URL_PARAM = "__posthog_session_id";

// posthog-js only adopts a bootstrap session id that is a UUIDv7; anything
// else would be dropped (or worse, adopted with a broken embedded timestamp),
// so refuse to decorate with an invalid id.
const UUID_V7_REGEX =
  /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function isUuidV7(value: string): boolean {
  return UUID_V7_REGEX.test(value);
}

const STITCHABLE_REGIONS: readonly CloudRegion[] = ["us", "eu"];

/** Exact origins of the PostHog web app that outbound links may be decorated for. */
export function getStitchableOrigins(includeDev: boolean): string[] {
  const regions = includeDev
    ? [...STITCHABLE_REGIONS, "dev" as const]
    : STITCHABLE_REGIONS;
  return regions.map((region) => new URL(getCloudUrlFromRegion(region)).origin);
}

/**
 * Append the PostHog session id to a URL when, and only when, it points at the
 * PostHog web app. The session id is identifying, so it must never reach other
 * hosts (including lookalike domains); the origin check is exact membership,
 * not a suffix match. Overwrites any pre-existing value of the param so a
 * crafted link cannot smuggle a foreign session id through.
 */
export function appendSessionIdIfPostHogUrl(
  url: string,
  sessionId: string,
  allowedOrigins: readonly string[],
): string {
  if (!isUuidV7(sessionId)) {
    return url;
  }

  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return url;
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return url;
  }
  if (!allowedOrigins.includes(parsed.origin)) {
    return url;
  }

  parsed.searchParams.set(POSTHOG_SESSION_ID_URL_PARAM, sessionId);
  return parsed.toString();
}
