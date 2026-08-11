import type { CanvasCapabilities } from "@posthog/shared";
import type {
  CanvasCaptureInput,
  CanvasLoadInsightInput,
} from "./freeformSchemas";

export function assertCanvasCapability(
  capabilities: CanvasCapabilities | undefined,
  method: string,
  payload: unknown,
): void {
  if (!capabilities) {
    throw new Error("Canvas capability manifest is unavailable");
  }

  switch (method) {
    case "query":
      if (!capabilities.posthog.inlineQueries) {
        throw new Error("Inline queries are not allowed by this canvas");
      }
      return;
    case "loadInsight":
      if (
        !capabilities.posthog.insights.includes(
          (payload as CanvasLoadInsightInput)?.shortId,
        )
      ) {
        throw new Error("Insight is not allowed by this canvas");
      }
      return;
    case "capture":
      if (
        !capabilities.posthog.captureEvents.includes(
          (payload as CanvasCaptureInput)?.event,
        )
      ) {
        throw new Error("Event capture is not allowed by this canvas");
      }
      return;
    default:
      throw new Error(`Method "${method}" is not allowed by this canvas`);
  }
}
