import type { useHostTRPC } from "@posthog/host-router/react";
import type { QueryClient } from "@tanstack/react-query";

type HostTRPC = ReturnType<typeof useHostTRPC>;

/**
 * Invalidate every scoped query hanging off one canvas: the record
 * (dashboards.get), its build lifecycle, its version history, and its source
 * (every version of it — `queryFilter({ id })` partial-matches the versioned
 * keys). One helper so revert, the generation sync-end sweep, and home-canvas
 * reset all refresh the same set instead of drifting.
 */
export function invalidateCanvasLifecycle(
  queryClient: QueryClient,
  trpc: HostTRPC,
  dashboardId: string,
): Promise<void> {
  const id = dashboardId;
  return Promise.all([
    queryClient.invalidateQueries(trpc.dashboards.get.queryFilter({ id })),
    queryClient.invalidateQueries(trpc.dashboards.builds.queryFilter({ id })),
    queryClient.invalidateQueries(trpc.dashboards.versions.queryFilter({ id })),
    queryClient.invalidateQueries(trpc.dashboards.drafts.queryFilter({ id })),
    queryClient.invalidateQueries(trpc.dashboards.source.queryFilter({ id })),
  ]).then(() => undefined);
}
