import {
  type CanvasBuildLifecycle,
  hasActiveCanvasBuild,
} from "@posthog/core/canvas/canvasBuildSchemas";
import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";

// Poll while a build is in flight (publishes queue a server-side build), then
// settle down — the lifecycle only changes again on the next publish.
const ACTIVE_POLL_MS = 2_000;
// While a generation is in flight but no build is active yet, poll at the
// canvas-record cadence — we're only waiting for the agent's publish to queue
// a build, and the record poll runs at this same rate.
const GENERATING_POLL_MS = 4_000;

/**
 * A canvas's build lifecycle, polled while a build is queued or running — OR
 * while the caller says a generation is in flight (`generating`): an agent's
 * publish lands server-side, so without that signal the client would never
 * observe the build the agent just queued.
 */
export function useCanvasBuilds(
  dashboardId: string | undefined,
  options?: { enabled?: boolean; generating?: boolean; versionId?: string },
): {
  lifecycle: CanvasBuildLifecycle | undefined;
  isLoading: boolean;
  /** True once the fetch has failed after its retries — lets a caller tell a
   * permanently broken request (e.g. a deleted component canvas) from a slow
   * one, so it can show an error instead of an endless spinner. */
  isError: boolean;
  /** Epoch ms the current lifecycle data was fetched — signed artifact URLs
   * are minted per fetch, so this is the pinned URL's mint time. */
  dataUpdatedAt: number;
  /** Re-run the fetch, for a retry control on the error state. */
  refetch: () => void;
} {
  const trpc = useHostTRPC();
  const generating = options?.generating ?? false;
  const { data, isLoading, isError, dataUpdatedAt, refetch } = useQuery(
    trpc.dashboards.builds.queryOptions(
      { id: dashboardId ?? "", versionId: options?.versionId },
      {
        enabled: !!dashboardId && (options?.enabled ?? true),
        staleTime: ACTIVE_POLL_MS,
        refetchInterval: (query) => {
          if (query.state.data && hasActiveCanvasBuild(query.state.data)) {
            return ACTIVE_POLL_MS;
          }
          return generating ? GENERATING_POLL_MS : false;
        },
      },
    ),
  );
  return {
    lifecycle: data,
    isLoading,
    isError,
    dataUpdatedAt,
    refetch: () => {
      void refetch();
    },
  };
}
