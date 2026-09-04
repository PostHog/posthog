import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { resolveServiceOptional } from "@posthog/di/container";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import {
  ANALYTICS_TRACKER,
  type AnalyticsTracker,
} from "../../shell/analytics";
import type { EvidenceLinkTarget } from "../../utils/evidenceLinks";
import { type EvidenceCardData, fetchEvidencePreview } from "./evidencePreview";

// Optional resolution: the quick-ask panel binds no ANALYTICS_TRACKER, and
// tracking must no-op there, not throw.
function tracker(): AnalyticsTracker | null {
  return resolveServiceOptional<AnalyticsTracker>(ANALYTICS_TRACKER);
}

export function trackEvidencePreviewShown(kind: string, cached: boolean): void {
  tracker()?.track(ANALYTICS_EVENTS.EVIDENCE_PREVIEW_SHOWN, {
    kind,
    cache: cached ? "hit" : "miss",
  });
}

function trackEvidencePreviewReady(
  kind: string,
  source: "hover" | "prefetch",
  latencyMs: number,
  hasPreview: boolean,
): void {
  tracker()?.track(ANALYTICS_EVENTS.EVIDENCE_PREVIEW_READY, {
    kind,
    source,
    latency_ms: latencyMs,
    has_preview: hasPreview,
  });
}

function trackEvidencePreviewFailed(
  kind: string,
  source: "hover" | "prefetch",
  latencyMs: number,
): void {
  tracker()?.track(ANALYTICS_EVENTS.EVIDENCE_PREVIEW_FAILED, {
    kind,
    source,
    latency_ms: latencyMs,
  });
}

export async function fetchEvidencePreviewTimed(
  client: PostHogAPIClient,
  target: EvidenceLinkTarget,
  source: "hover" | "prefetch",
): Promise<EvidenceCardData | null> {
  const startedAt = performance.now();
  try {
    const preview = await fetchEvidencePreview(client, target);
    trackEvidencePreviewReady(
      target.kind,
      source,
      Math.round(performance.now() - startedAt),
      preview !== null,
    );
    return preview;
  } catch (error) {
    trackEvidencePreviewFailed(
      target.kind,
      source,
      Math.round(performance.now() - startedAt),
    );
    throw error;
  }
}
