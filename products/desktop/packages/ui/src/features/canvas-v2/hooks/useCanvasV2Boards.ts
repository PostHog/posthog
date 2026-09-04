import { useHostTRPC } from "@posthog/host-router/react";
import type { CanvasV2BoardSummary } from "@posthog/shared";
import {
  SPACE_QUERY_GC_TIME_MS,
  SPACE_QUERY_REFETCH_INTERVAL_MS,
  SPACE_QUERY_STALE_TIME_MS,
} from "@posthog/ui/features/canvas/hooks/spaceQueryPolicy";
import { useQuery } from "@tanstack/react-query";

interface CanvasV2BoardsResult {
  boards: CanvasV2BoardSummary[];
  isLoading: boolean;
  isError: boolean;
}

/** The boards of one space, newest change first. */
export function useCanvasV2Boards(channelId: string): CanvasV2BoardsResult {
  const trpc = useHostTRPC();
  const { data, isLoading, isError } = useQuery(
    trpc.canvasV2.list.queryOptions(
      { channelId },
      {
        enabled: channelId.length > 0,
        gcTime: SPACE_QUERY_GC_TIME_MS,
        refetchInterval: SPACE_QUERY_REFETCH_INTERVAL_MS,
        staleTime: SPACE_QUERY_STALE_TIME_MS,
      },
    ),
  );
  return { boards: data ?? [], isLoading, isError };
}

/** Every board this person can see, in every space. */
export function useAllCanvasV2Boards(): CanvasV2BoardsResult {
  const trpc = useHostTRPC();
  const { data, isLoading, isError } = useQuery(
    trpc.canvasV2.listAll.queryOptions(undefined, {
      gcTime: SPACE_QUERY_GC_TIME_MS,
      refetchInterval: SPACE_QUERY_REFETCH_INTERVAL_MS,
      staleTime: SPACE_QUERY_STALE_TIME_MS,
    }),
  );
  return { boards: data ?? [], isLoading, isError };
}
