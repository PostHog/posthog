import {
  buildChannelItems,
  type ChannelItemModel,
} from "@posthog/core/canvas/channelItems";
import type { Task } from "@posthog/shared/domain-types";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { usePinnedTasks } from "@posthog/ui/features/sidebar/usePinnedTasks";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useRef } from "react";
import {
  SPACE_QUERY_GC_TIME_MS,
  SPACE_QUERY_STALE_TIME_MS,
} from "./spaceQueryPolicy";

/**
 * Its own key rather than the channel feed's: the tree asks for a short page,
 * and handing that truncated list to the space's own feed through a shared
 * cache would quietly cut it off at the same length.
 */
const spaceTreeTasksQueryKey = (spaceId: string) =>
  ["space-tree-tasks", spaceId] as const;

/** How many sessions a space shows when expanded in the list. */
export const RECENT_TASKS_PER_SPACE = 5;

/**
 * A little more than the tree shows, because archived tasks are filtered out
 * client-side. Nothing like the feed's 500: a dozen open spaces would otherwise
 * pull thousands of full task records to draw sixty rows.
 */
const TREE_FETCH_LIMIT = 20;

/** One page of a space's sessions, with the total the page was cut from. */
interface SpaceTaskPage {
  tasks: Task[];
  count: number;
}

const NO_PAGE: SpaceTaskPage = { tasks: [], count: 0 };

/** A space's rows: the newest few, and how many sessions it holds in all. */
export interface SpaceTasks {
  items: ChannelItemModel[];
  /** Everything in the space, not just the rows shown. */
  total: number;
}

/**
 * One object for every space with nothing to show, so a collapsed row's props
 * are identical between renders and its memo holds.
 */
export const NO_TASKS: SpaceTasks = { items: [], total: 0 };

/** What a space's rows were built from, so they can be reused unchanged. */
interface CachedSpaceTasks {
  page: SpaceTaskPage;
  archivedTaskIds: ReadonlySet<string>;
  pinnedTaskIds: ReadonlySet<string>;
  built: SpaceTasks;
}

/**
 * Module-level so `useQueries` can memoize on it: an inline combine is a new
 * function every render, which makes every render rebuild the lists — and with
 * them the item models and every row's props.
 */
function combineTaskPages(
  queries: { data?: SpaceTaskPage }[],
): SpaceTaskPage[] {
  return queries.map((query) => query.data ?? NO_PAGE);
}

// Slower than the open channel's own feed (5s): the tree is a glance at what's
// been happening, not the surface you watch a run on, and every expanded space
// pays this interval.
const SPACE_TREE_POLL_INTERVAL_MS = 30_000;

/**
 * The newest sessions in each of the given spaces, keyed by space id, as the
 * same item model the space's own session list is built from — so a tree row
 * can wear the status dot and badges those rows do.
 *
 * One query per space, and only for the spaces actually expanded. The flat task
 * list can't stand in for this: it is capped, and most of its rows carry no
 * channel at all.
 */
export function useRecentSpaceTasks(
  spaceIds: string[],
): Map<string, SpaceTasks> {
  const client = useOptionalAuthenticatedClient();
  const archivedTaskIds = useArchivedTaskIds();
  const { pinnedTaskIds } = usePinnedTasks();

  const pagePerSpace = useQueries({
    queries: spaceIds.map((spaceId) => ({
      queryKey: spaceTreeTasksQueryKey(spaceId),
      queryFn: async (): Promise<SpaceTaskPage> => {
        if (!client) throw new Error("Not authenticated");
        return (await client.getTasksPage({
          channel: spaceId,
          limit: TREE_FETCH_LIMIT,
        })) as SpaceTaskPage;
      },
      enabled: !!client,
      gcTime: SPACE_QUERY_GC_TIME_MS,
      meta: AUTH_SCOPED_QUERY_META,
      refetchInterval: SPACE_TREE_POLL_INTERVAL_MS,
      staleTime: SPACE_QUERY_STALE_TIME_MS,
    })),
    combine: combineTaskPages,
  });

  // Per-space memo, not one over the whole map: opening another space changes
  // the id list, and rebuilding every space's items from that would hand each
  // already-open row a new array — enough to re-render every session row in the
  // tree on every expand.
  const cache = useRef(new Map<string, CachedSpaceTasks>());

  return useMemo(() => {
    const bySpace = new Map<string, SpaceTasks>();
    spaceIds.forEach((spaceId, index) => {
      const page = pagePerSpace[index] ?? NO_PAGE;
      const cached = cache.current.get(spaceId);
      if (
        cached &&
        cached.page === page &&
        cached.archivedTaskIds === archivedTaskIds &&
        cached.pinnedTaskIds === pinnedTaskIds
      ) {
        bySpace.set(spaceId, cached.built);
        return;
      }
      // Canvases are the space's own list to show; the tree answers "what has
      // been running here lately".
      const available = buildChannelItems({
        dashboards: [],
        feedTasks: page.tasks,
        archivedTaskIds,
        pinnedTaskIds,
        ownedBy: null,
      });
      // A page that came back short is the whole space, so the count is exact
      // once the archived ones are dropped. A full page falls back to the
      // server's total, which still counts anything archived in it.
      const built: SpaceTasks = {
        items: available.slice(0, RECENT_TASKS_PER_SPACE),
        total:
          page.tasks.length < TREE_FETCH_LIMIT ? available.length : page.count,
      };
      cache.current.set(spaceId, {
        page,
        archivedTaskIds,
        pinnedTaskIds,
        built,
      });
      bySpace.set(spaceId, built);
    });
    return bySpace;
  }, [spaceIds, pagePerSpace, archivedTaskIds, pinnedTaskIds]);
}

/**
 * Warm a space's sessions before it is expanded — from the row's hover, the way
 * the channel pane's own queries are warmed. A cold expand pays a round trip
 * (over a second on a slow one); a warm one renders from cache.
 */
export function usePrefetchSpaceTasks(): (spaceId: string) => void {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();

  return useCallback(
    (spaceId: string) => {
      if (!client) return;
      void queryClient.prefetchQuery({
        queryKey: spaceTreeTasksQueryKey(spaceId),
        queryFn: async (): Promise<SpaceTaskPage> =>
          (await client.getTasksPage({
            channel: spaceId,
            limit: TREE_FETCH_LIMIT,
          })) as SpaceTaskPage,
        gcTime: SPACE_QUERY_GC_TIME_MS,
        meta: AUTH_SCOPED_QUERY_META,
        // Same staleTime as the live query, so a warm cache is a no-op.
        staleTime: SPACE_QUERY_STALE_TIME_MS,
      });
    },
    [client, queryClient],
  );
}
