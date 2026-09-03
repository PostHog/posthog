import type { BoardApi } from "@posthog/core/canvas-v2/boardSync";
import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { useMemo } from "react";

/** The board endpoints of the host, in the shape the sync client expects. */
export function useBoardApi(): BoardApi {
  return useMemo<BoardApi>(() => {
    const trpc = (): HostTrpcClient =>
      resolveService<HostTrpcClient>(HOST_TRPC_CLIENT);
    return {
      get: (id) => trpc().canvasV2.get.query({ id }),
      opsSince: (id, since, limit) =>
        trpc().canvasV2.opsSince.query({ id, since, limit }),
      appendOps: (id, input) =>
        trpc().canvasV2.appendOps.mutate({ id, ...input }),
    };
  }, []);
}
