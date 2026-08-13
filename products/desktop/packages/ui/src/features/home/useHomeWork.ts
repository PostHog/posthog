import type { HomeWork } from "@posthog/core/home/homeSchemas";
import { useHostTRPC } from "@posthog/host-router/react";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import {
  AUTH_SCOPED_QUERY_META,
  useCurrentUser,
} from "@posthog/ui/features/auth/useCurrentUser";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

// Home is a landing page, not a live monitor: the work behind it changes on the
// scale of a working day, so it refetches on mount and otherwise sits still.
const STALE_TIME_MS = 60_000;
/** How many rows each group keeps. Home shows a handful and links out. */
const GROUP_LIMIT = 6;

const EMPTY_WORK: HomeWork = {
  featureFlags: [],
  experiments: [],
  unavailable: [],
};

/**
 * The feature flags and experiments Home opens on, marked with whether they are
 * the viewer's own. Waits for the current user so ownership is known on the
 * first paint rather than reshuffling the page a moment later.
 */
export function useHomeWork(options?: { enabled?: boolean }): {
  work: HomeWork;
  isLoading: boolean;
} {
  const trpc = useHostTRPC();
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser, isLoading: userLoading } = useCurrentUser({
    client,
  });
  const enabled = (options?.enabled ?? true) && !userLoading;

  const { data, isLoading } = useQuery(
    trpc.home.work.queryOptions(
      { viewerId: currentUser?.id ?? null, limit: GROUP_LIMIT },
      {
        enabled,
        meta: AUTH_SCOPED_QUERY_META,
        staleTime: STALE_TIME_MS,
      },
    ),
  );

  return { work: data ?? EMPTY_WORK, isLoading: userLoading || isLoading };
}

/**
 * Warm Home's work cache from somewhere else in the app (the rail's Home
 * button on hover), so the page paints its sections instead of its skeletons.
 * Same staleTime as the live query, so it no-ops when the data is fresh.
 */
export function usePrefetchHomeWork(): () => void {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });
  const viewerId = currentUser?.id ?? null;

  return useCallback(() => {
    void queryClient.prefetchQuery(
      trpc.home.work.queryOptions(
        { viewerId, limit: GROUP_LIMIT },
        { meta: AUTH_SCOPED_QUERY_META, staleTime: STALE_TIME_MS },
      ),
    );
  }, [trpc, queryClient, viewerId]);
}
