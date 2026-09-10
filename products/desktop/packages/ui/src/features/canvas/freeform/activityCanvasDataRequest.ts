import { canvasActivityFeedInput } from "@posthog/core/canvas/freeformSchemas";
import type { QueryClient } from "@tanstack/react-query";
import { handleFreeformDataRequest } from "./freeformDataBridge";

/**
 * The data bridge of a canvas that draws the Activity page.
 *
 * `activityFeed` is answered from the signed-in viewer's own feed. The canvas
 * names no person and no space, so it can only ever read the activity of
 * whoever is looking at it. Every other method goes to the shared bridge,
 * scoped to the canvas that is drawing, exactly as a grid widget's calls are.
 */
export function createActivityCanvasDataRequest({
  canvasId,
  sourceVersionId,
  readFeed,
  queryClient,
}: {
  canvasId: string;
  sourceVersionId: string | undefined;
  readFeed: (limit?: number) => unknown;
  queryClient: QueryClient;
}): (method: string, payload: unknown) => Promise<unknown> {
  return async (method, payload) => {
    if (method === "activityFeed") {
      const input = canvasActivityFeedInput.parse(payload ?? {});
      return readFeed(input.limit);
    }
    return handleFreeformDataRequest(method, payload, queryClient, {
      dashboardId: canvasId,
      sourceVersionId,
    });
  };
}
