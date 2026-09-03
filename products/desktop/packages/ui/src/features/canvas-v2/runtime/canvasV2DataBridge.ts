import {
  CANVAS_V2_MAX_STATE_VALUE_BYTES,
  type CanvasV2DataMethod,
  type CanvasV2Op,
  type CanvasV2Snapshot,
  estimateJsonBytes,
} from "@posthog/shared";
import { handleFreeformDataRequest } from "@posthog/ui/features/canvas/freeform/freeformDataBridge";
import type { QueryClient } from "@tanstack/react-query";

export interface CanvasV2DataBridgeContext {
  boardId: string;
  queryClient: QueryClient;
  getSnapshot: () => CanvasV2Snapshot;
  applyLocal: (ops: CanvasV2Op[]) => void;
}

// Resolves a `ph.*` request from a board frame. Reads go through the existing
// freeform bridge (same cache, same host call); shared state is the board's own
// synced state, so it is served from the snapshot and written as an op.
export async function handleCanvasV2DataRequest(
  method: CanvasV2DataMethod,
  payload: unknown,
  ctx: CanvasV2DataBridgeContext,
): Promise<unknown> {
  switch (method) {
    case "query":
    case "loadInsight":
      // Neither case reads the dashboard context, so none is passed.
      return handleFreeformDataRequest(method, payload, ctx.queryClient);
    case "stateGet": {
      const key = readKey(payload, "ph.state.get(key) requires a key");
      return ctx.getSnapshot().state[key] ?? null;
    }
    case "stateSet": {
      const key = readKey(payload, "ph.state.set(key, value) requires a key");
      const raw = (payload as { value?: unknown }).value;
      const value = raw === undefined ? null : raw;
      if (estimateJsonBytes(value) > CANVAS_V2_MAX_STATE_VALUE_BYTES) {
        throw new Error(
          `ph.state.set(key, value) is limited to ${Math.floor(CANVAS_V2_MAX_STATE_VALUE_BYTES / 1024)} KB per value`,
        );
      }
      ctx.applyLocal([{ type: "set_state", key, value }]);
      return { ok: true };
    }
    case "stateList":
      return Object.entries(ctx.getSnapshot().state).map(([key, value]) => ({
        key,
        value,
      }));
    default:
      throw new Error(`ph.${method} is not available on Canvases v2 yet`);
  }
}

function readKey(payload: unknown, message: string): string {
  const key = (payload as { key?: unknown } | null)?.key;
  if (typeof key !== "string" || key.length === 0) throw new Error(message);
  return key;
}
