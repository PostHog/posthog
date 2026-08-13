import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import {
  buildHomeRows,
  type HomeRow,
  type HomeSpaceWork,
} from "@posthog/core/home/homeRows";
import { useHostTRPC } from "@posthog/host-router/react";
import type { Task } from "@posthog/shared/domain-types";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import {
  SPACE_QUERY_GC_TIME_MS,
  SPACE_QUERY_STALE_TIME_MS,
} from "@posthog/ui/features/canvas/hooks/spaceQueryPolicy";
import {
  type Channel,
  useChannels,
} from "@posthog/ui/features/canvas/hooks/useChannels";
import { useHomeProjectsStore } from "@posthog/ui/features/home/homeProjectsStore";
import { usePinnedTasks } from "@posthog/ui/features/sidebar/usePinnedTasks";
import { useQueries } from "@tanstack/react-query";
import { useMemo } from "react";

/**
 * How much of a space's history the table reaches back over. Far more than the
 * sidebar tree's page, because this is the surface you scan a quarter's work
 * on, and far short of everything, because a busy org would otherwise pull tens
 * of thousands of task records to draw one screen.
 */
const TASKS_PER_SPACE = 100;

/** Slower than a space's own feed: the home table is a glance, not a monitor. */
const HOME_POLL_INTERVAL_MS = 30_000;

const homeSpaceTasksQueryKey = (spaceId: string) =>
  ["home-space-tasks", spaceId] as const;

/**
 * The spaces the table covers: the ones this reader pinned, plus their own
 * private space, which is pinned by definition.
 */
export function usePinnedSpaces(): { spaces: Channel[]; isLoading: boolean } {
  const { channels, isLoading } = useChannels();
  const spaces = useMemo(
    () =>
      channels.filter(
        (channel) => channel.starred || channel.channelType === "personal",
      ),
    [channels],
  );
  return { spaces, isLoading };
}

/** One list per space, and whether any space is still on its first fetch. */
interface SpaceLists<T> {
  lists: T[][];
  pending: boolean;
}

// Module scope so `useQueries` can memoize on them: an inline combine is a new
// function every render, which rebuilds every row on every render with it.
function combineTaskPages(
  queries: { data?: { tasks: Task[] }; isPending: boolean }[],
): SpaceLists<Task> {
  return {
    lists: queries.map((query) => query.data?.tasks ?? []),
    pending: queries.some((query) => query.isPending),
  };
}

function combineCanvasLists(
  queries: { data?: DashboardRecord[]; isPending: boolean }[],
): SpaceLists<DashboardRecord> {
  return {
    lists: queries.map((query) => query.data ?? []),
    pending: queries.some((query) => query.isPending),
  };
}

/**
 * Every pinned space's sessions and canvases, as one row per piece of work.
 *
 * The fan-out is one pair of queries per pinned space rather than a single flat
 * list, because the flat tasks endpoint is capped and most of its rows carry no
 * space at all, so it cannot answer "what is in these spaces".
 */
export function useHomeRows(): { rows: HomeRow[]; isLoading: boolean } {
  const client = useOptionalAuthenticatedClient();
  const trpc = useHostTRPC();
  const { spaces, isLoading: spacesLoading } = usePinnedSpaces();
  const archivedTaskIds = useArchivedTaskIds();
  const { pinnedTaskIds } = usePinnedTasks();
  const projects = useHomeProjectsStore((state) => state.projects);
  const notes = useHomeProjectsStore((state) => state.notes);
  const filing = useHomeProjectsStore((state) => state.filing);

  const tasksPerSpace = useQueries({
    queries: spaces.map((space) => ({
      queryKey: homeSpaceTasksQueryKey(space.id),
      queryFn: async () => {
        if (!client) throw new Error("Not authenticated");
        return await client.getTasksPage({
          channel: space.id,
          limit: TASKS_PER_SPACE,
        });
      },
      enabled: !!client,
      gcTime: SPACE_QUERY_GC_TIME_MS,
      meta: AUTH_SCOPED_QUERY_META,
      refetchInterval: HOME_POLL_INTERVAL_MS,
      staleTime: SPACE_QUERY_STALE_TIME_MS,
    })),
    combine: combineTaskPages,
  });

  const canvasesPerSpace = useQueries({
    queries: spaces.map((space) =>
      trpc.dashboards.list.queryOptions(
        { channelId: space.id },
        {
          gcTime: SPACE_QUERY_GC_TIME_MS,
          meta: AUTH_SCOPED_QUERY_META,
          refetchInterval: HOME_POLL_INTERVAL_MS,
          staleTime: SPACE_QUERY_STALE_TIME_MS,
        },
      ),
    ),
    combine: combineCanvasLists,
  });

  const work = useMemo<HomeSpaceWork[]>(
    () =>
      spaces.map((space, index) => ({
        space: {
          id: space.id,
          name: space.name,
          personal: space.channelType === "personal",
        },
        tasks: tasksPerSpace.lists[index] ?? [],
        canvases: canvasesPerSpace.lists[index] ?? [],
      })),
    [spaces, tasksPerSpace, canvasesPerSpace],
  );

  const rows = useMemo(
    () =>
      buildHomeRows({
        work,
        projects: Object.values(projects),
        notes: Object.values(notes),
        filing,
        archivedTaskIds,
        pinnedTaskIds,
      }),
    [work, projects, notes, filing, archivedTaskIds, pinnedTaskIds],
  );

  return {
    rows,
    // Loading until the spaces are known and every one of them has answered
    // once. An empty table before that is "not asked yet", not "nothing here",
    // and the two want very different screens.
    isLoading:
      spacesLoading || tasksPerSpace.pending || canvasesPerSpace.pending,
  };
}
