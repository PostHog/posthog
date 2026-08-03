import {
  type CanvasBuildLifecycle,
  hasActiveCanvasBuild,
} from "@posthog/core/canvas/canvasBuildSchemas";
import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";

// Poll while a build is in flight (publishes queue a server-side build), then
// settle down — the lifecycle only changes again on the next publish.
const ACTIVE_POLL_MS = 2_000;

/**
 * A canvas's build lifecycle, polled while a build is queued or running — OR
 * while the caller says a generation is in flight (`generating`): an agent's
 * publish lands server-side, so without that signal the client would never
 * observe the build the agent just queued.
 */
export function useCanvasBuilds(
  dashboardId: string | undefined,
  options?: { enabled?: boolean; generating?: boolean },
): {
  lifecycle: CanvasBuildLifecycle | undefined;
  isLoading: boolean;
  /** Epoch ms the current lifecycle data was fetched — signed artifact URLs
   * are minted per fetch, so this is the pinned URL's mint time. */
  dataUpdatedAt: number;
} {
  const trpc = useHostTRPC();
  const generating = options?.generating ?? false;
  const { data, isLoading, dataUpdatedAt } = useQuery(
    trpc.dashboards.builds.queryOptions(
      { id: dashboardId ?? "" },
      {
        enabled: !!dashboardId && (options?.enabled ?? true),
        staleTime: ACTIVE_POLL_MS,
        refetchInterval: (query) =>
          generating ||
          (query.state.data && hasActiveCanvasBuild(query.state.data))
            ? ACTIVE_POLL_MS
            : false,
      },
    ),
  );
  return { lifecycle: data, isLoading, dataUpdatedAt };
}
