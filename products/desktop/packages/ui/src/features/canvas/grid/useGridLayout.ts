import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import type {
  CanvasLayoutResult,
  LayoutOperation,
} from "@posthog/core/canvas/gridLayoutSchemas";
import { useHostTRPC } from "@posthog/host-router/react";
import { toastError } from "@posthog/ui/features/notifications/errorDetails";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

// Poll fast while any placement is being agent-filled (the agent patches the
// layout server-side), otherwise slowly — other viewers/agents can still edit.
const GENERATING_POLL_MS = 3_000;
const IDLE_POLL_MS = 20_000;

export function useGridLayout(canvasId: string | undefined): {
  layout: CanvasLayoutResult["layout"] | undefined;
  currentVersionId: string | null;
  isLoading: boolean;
} {
  const trpc = useHostTRPC();
  const { data, isLoading } = useQuery(
    trpc.dashboards.layout.queryOptions(
      { id: canvasId ?? "" },
      {
        enabled: !!canvasId,
        staleTime: GENERATING_POLL_MS,
        refetchInterval: (query) =>
          query.state.data?.layout.placements.some(
            (placement) => placement.status === "generating",
          )
            ? GENERATING_POLL_MS
            : IDLE_POLL_MS,
      },
    ),
  );
  return {
    layout: data?.layout,
    currentVersionId: data?.currentVersionId ?? null,
    isLoading,
  };
}

/**
 * Guarded surgical writes to a grid canvas's layout. On success the layout
 * cache adopts the server's document; on any failure (including a 409 from a
 * concurrent edit) the layout is refetched so the surface rebases on the real
 * head instead of retrying blind.
 */
export function usePatchLayout(canvasId: string): {
  patch: (
    operations: LayoutOperation[],
    expectedCurrentVersionId: string | null,
    prompt?: string,
  ) => Promise<CanvasLayoutResult | null>;
  isPatching: boolean;
} {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();
  const layoutKey = trpc.dashboards.layout.queryKey({ id: canvasId });
  const { mutateAsync, isPending } = useMutation(
    trpc.dashboards.patchLayout.mutationOptions({
      onSuccess: (result) => {
        queryClient.setQueryData(layoutKey, result);
      },
      onError: (error) => {
        toastError("Couldn't update the canvas layout", error);
        void queryClient.invalidateQueries({ queryKey: layoutKey });
      },
    }),
  );
  const patch = useCallback(
    async (
      operations: LayoutOperation[],
      expectedCurrentVersionId: string | null,
      prompt?: string,
    ) => {
      try {
        return await mutateAsync({
          id: canvasId,
          operations,
          prompt,
          expectedCurrentVersionId,
        });
      } catch {
        // Already surfaced by onError; callers treat null as "rebase and retry".
        return null;
      }
    },
    [mutateAsync, canvasId],
  );
  return { patch, isPatching: isPending };
}

export function useComponentStore(
  search: string,
  options?: { enabled?: boolean },
): {
  components: DashboardRecord[];
  isLoading: boolean;
} {
  const trpc = useHostTRPC();
  const { data, isLoading } = useQuery(
    trpc.dashboards.listComponents.queryOptions(
      { search: search || undefined },
      { staleTime: 30_000, enabled: options?.enabled ?? true },
    ),
  );
  return { components: data ?? [], isLoading };
}
