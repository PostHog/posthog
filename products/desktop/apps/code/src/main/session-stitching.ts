import {
  appendSessionIdIfPostHogUrl,
  getStitchableOrigins,
} from "@posthog/shared";
import { posthogNodeAnalytics } from "./platform-adapters/posthog-analytics";
import { isDevBuild } from "./utils/env";

/**
 * Decorate an outbound URL with the renderer's PostHog session id when it
 * points at the PostHog web app, so events and the recording captured there
 * carry the same $session_id as this app's (cross-surface session stitching).
 * Runs at open time, never at link build time, which keeps copyable share
 * links free of session ids. The renderer only pushes a session id while the
 * stitching feature flag is on, so this is a no-op otherwise.
 */
export function decorateOutboundUrl(url: string): string {
  const sessionId = posthogNodeAnalytics.getRendererSessionId();
  if (!sessionId) {
    return url;
  }
  return appendSessionIdIfPostHogUrl(
    url,
    sessionId,
    getStitchableOrigins(isDevBuild()),
  );
}
