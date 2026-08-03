import type { CanvasCapabilities } from "@posthog/shared";
import type {
  CanvasCaptureInput,
  CanvasLoadInsightInput,
} from "./freeformSchemas";

// Capability gating for canvas `ph.*` data requests. A published build's
// manifest freezes the capabilities its source declared; view mode holds every
// request to that allowlist. The interactive/edit path never asserts — the
// author's own client has full data access while iterating.
//
// `capabilities` may be undefined: the manifest hasn't loaded yet, or the
// canvas is client-rendered from head source (no build, so no manifest at
// all). Rejecting in that window would hard-fail every read during a purely
// transient gap, so undefined means "allow" — enforcement starts the moment a
// manifest's capabilities exist.
export function assertCanvasCapability(
  capabilities: CanvasCapabilities | undefined,
  method: string,
  payload: unknown,
): void {
  if (!capabilities) return;
  if (method === "query" && !capabilities.posthog.inlineQueries) {
    throw new Error("Inline queries are not allowed by this canvas");
  }
  if (
    method === "loadInsight" &&
    !capabilities.posthog.insights.includes(
      (payload as CanvasLoadInsightInput)?.shortId,
    )
  ) {
    throw new Error("Insight is not allowed by this canvas");
  }
  if (
    method === "capture" &&
    !capabilities.posthog.captureEvents.includes(
      (payload as CanvasCaptureInput)?.event,
    )
  ) {
    throw new Error("Event capture is not allowed by this canvas");
  }
}
