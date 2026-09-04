import { useHostTRPC } from "@posthog/host-router/react";
import type { CanvasV2BoardSummary } from "@posthog/shared";
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
      { enabled: channelId.length > 0, staleTime: 5_000 },
    ),
  );
  return { boards: data ?? [], isLoading, isError };
}

/** Every board this person can see, in every space. */
export function useAllCanvasV2Boards(): CanvasV2BoardsResult {
  const trpc = useHostTRPC();
  const { data, isLoading, isError } = useQuery(
    trpc.canvasV2.listAll.queryOptions(undefined, { staleTime: 5_000 }),
  );
  return { boards: data ?? [], isLoading, isError };
}
