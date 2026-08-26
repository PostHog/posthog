import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { resolveServiceOptional } from "@posthog/di/container";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import {
  ANALYTICS_TRACKER,
  type AnalyticsTracker,
} from "../../shell/analytics";
import type { EvidenceLinkTarget } from "../../utils/evidenceLinks";
import { type EvidenceCardData, fetchEvidencePreview } from "./evidencePreview";

/**
 * Instrumentation around evidence (insight link) preview loading:
 * `shown` when the hover card opens, `ready`/`failed` when a load settles,
 * each with only the kind slug and the load latency — never the referenced
 * id, name, query text, or result data (see analytics-events.ts).
 *
 * The tracker is resolved through the optional root seam rather than
 * useService: chips render on the quick-ask panel too, whose container binds
 * no ANALYTICS_TRACKER, and tracking must no-op there instead of crashing.
 */
function tracker(): AnalyticsTracker | null {
  return resolveServiceOptional<AnalyticsTracker>(ANALYTICS_TRACKER);
}

/** The hover card opened. `cached` tells whether data was already resolved. */
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

/**
 * fetchEvidencePreview with ready/failed tracking and load latency. Shared
 * by the hover card (`source: "hover"`) and the viewport prefetch, so the
 * events attribute each load to what triggered it.
 */
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
