import type { BoardApi } from "@posthog/core/canvas-v2/boardSync";
import { useHostTRPCClient } from "@posthog/host-router/react";
import { useMemo } from "react";

/** The board endpoints of the host, in the shape the sync client expects. */
export function useBoardApi(): BoardApi {
  const trpc = useHostTRPCClient();
  return useMemo<BoardApi>(() => {
    return {
      get: (id) => trpc.canvasV2.get.query({ id }),
      opsSince: (id, since, limit) =>
        trpc.canvasV2.opsSince.query({ id, since, limit }),
      appendOps: (id, input) =>
        trpc.canvasV2.appendOps.mutate({ id, ...input }),
    };
  }, [trpc]);
}
