import {
  type CanvasBuildLifecycle,
  hasActiveCanvasBuild,
} from "@posthog/core/canvas/canvasBuildSchemas";
import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";

// Poll while a build is in flight (publishes queue a server-side build), then
// settle down — the lifecycle only changes again on the next publish.
const ACTIVE_POLL_MS = 2_000;

/** A canvas's build lifecycle, polled while a build is queued or running. */
export function useCanvasBuilds(
  dashboardId: string | undefined,
  options?: { enabled?: boolean },
): {
  lifecycle: CanvasBuildLifecycle | undefined;
  isLoading: boolean;
} {
  const trpc = useHostTRPC();
  const { data, isLoading } = useQuery(
    trpc.dashboards.builds.queryOptions(
      { id: dashboardId ?? "" },
      {
        enabled: !!dashboardId && (options?.enabled ?? true),
        staleTime: ACTIVE_POLL_MS,
        refetchInterval: (query) =>
          query.state.data && hasActiveCanvasBuild(query.state.data)
            ? ACTIVE_POLL_MS
            : false,
      },
    ),
  );
  return { lifecycle: data, isLoading };
}
