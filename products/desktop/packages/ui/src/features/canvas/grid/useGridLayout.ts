import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import { applyLayoutOperations } from "@posthog/core/canvas/gridLayoutOperations";
import type {
  CanvasLayoutResult,
  LayoutOperation,
} from "@posthog/core/canvas/gridLayoutSchemas";
import { useHostTRPC } from "@posthog/host-router/react";
import { toastError } from "@posthog/ui/features/notifications/errorDetails";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef } from "react";

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
 * Guarded surgical writes to a grid canvas's layout. The edit shows the moment
 * it is made: the operations are applied to the layout cache on the way out,
 * because rendering the server's document for the length of the round trip
 * snaps a dragged tile back to where it started. On success the cache adopts
 * the server's document; on any failure (including a 409 from a concurrent
 * edit) the layout is refetched so the surface rebases on the real head
 * instead of retrying blind.
 *
 * Patches run one at a time, each reading the head from the layout cache when
 * it is actually sent. Two gestures can finish before the first patch answers,
 * and sending both against the same head would have the server reject the
 * second as a conflict — losing that drag or resize on the rebase refetch.
 */
export function usePatchLayout(canvasId: string): {
  patch: (
    operations: LayoutOperation[],
    prompt?: string,
  ) => Promise<CanvasLayoutResult | null>;
  isPatching: boolean;
} {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();
  const { mutateAsync, isPending } = useMutation(
    trpc.dashboards.patchLayout.mutationOptions(),
  );
  // The tail of the patch queue. It never rejects, so one failed patch cannot
  // wedge the gestures behind it.
  const queue = useRef<Promise<CanvasLayoutResult | null>>(
    Promise.resolve(null),
  );
  // Edits the canvas already shows and the server has not acknowledged, oldest
  // first.
  const unacknowledged = useRef<LayoutOperation[][]>([]);
  const patch = useCallback(
    (operations: LayoutOperation[], prompt?: string) => {
      const key = trpc.dashboards.layout.queryKey({ id: canvasId });
      queryClient.setQueryData<CanvasLayoutResult>(key, (current) =>
        current
          ? {
              ...current,
              layout: applyLayoutOperations(current.layout, operations),
            }
          : current,
      );
      unacknowledged.current = [...unacknowledged.current, operations];
      const settled = () => {
        unacknowledged.current = unacknowledged.current.filter(
          (entry) => entry !== operations,
        );
      };
      const queued = queue.current.then(async () => {
        const head = queryClient.getQueryData<CanvasLayoutResult>(key);
        try {
          const result = await mutateAsync({
            id: canvasId,
            operations,
            prompt,
            // The optimistic write above leaves this field alone, so the guard
            // still names the head the server itself last minted.
            expectedCurrentVersionId: head?.currentVersionId ?? null,
          });
          settled();
          // The server's document, with any gesture made since still on top of
          // it: adopting it bare would snap those back for their own round trip.
          queryClient.setQueryData(key, {
            ...result,
            layout: unacknowledged.current.reduce(
              (layout, entry) => applyLayoutOperations(layout, entry),
              result.layout,
            ),
          });
          return result;
        } catch (error) {
          settled();
          toastError("Couldn't update the canvas layout", error);
          // Rebase before the next queued gesture is sent, and let callers
          // treat null as "this edit didn't land".
          await queryClient.invalidateQueries({ queryKey: key });
          return null;
        }
      });
      queue.current = queued;
      return queued;
    },
    [mutateAsync, canvasId, queryClient, trpc],
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
