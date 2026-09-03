import { useHostTRPC } from "@posthog/host-router/react";
import type { CanvasV2BoardSummary } from "@posthog/shared";
import { useQuery } from "@tanstack/react-query";

/** Every board of the current project, newest change first. */
export function useCanvasV2Boards(): {
  boards: CanvasV2BoardSummary[];
  isLoading: boolean;
  isError: boolean;
} {
  const trpc = useHostTRPC();
  const { data, isLoading, isError } = useQuery(
    trpc.canvasV2.list.queryOptions(undefined, { staleTime: 5_000 }),
  );
  return { boards: data ?? [], isLoading, isError };
}
