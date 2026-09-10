import { canvasTaskActivityInput } from "@posthog/core/canvas/freeformSchemas";
import type { QueryClient } from "@tanstack/react-query";
import { handleFreeformDataRequest } from "./freeformDataBridge";

/**
 * The data bridge of a canvas that draws a task's activity.
 *
 * `taskActivity` is answered from the task whose panel the canvas is mounted
 * in. The canvas names no task, so it can never read one its viewer did not
 * open. Every other method goes to the shared bridge, scoped to the canvas that
 * is drawing, exactly as a grid widget's calls are.
 */
export function createActivityCanvasDataRequest({
  canvasId,
  sourceVersionId,
  readActivity,
  queryClient,
}: {
  canvasId: string;
  sourceVersionId: string | undefined;
  readActivity: (limit?: number) => unknown;
  queryClient: QueryClient;
}): (method: string, payload: unknown) => Promise<unknown> {
  return async (method, payload) => {
    if (method === "taskActivity") {
      const input = canvasTaskActivityInput.parse(payload ?? {});
      return readActivity(input.limit);
    }
    return handleFreeformDataRequest(method, payload, queryClient, {
      dashboardId: canvasId,
      sourceVersionId,
    });
  };
}
