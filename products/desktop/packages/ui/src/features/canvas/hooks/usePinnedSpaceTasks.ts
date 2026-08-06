import {
  buildChannelItems,
  type ChannelItemModel,
} from "@posthog/core/canvas/channelItems";
import type { Task } from "@posthog/shared/domain-types";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { usePinnedTasks } from "@posthog/ui/features/sidebar/usePinnedTasks";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useQueries } from "@tanstack/react-query";
import { useMemo } from "react";
import { SPACE_QUERY_STALE_TIME_MS } from "./spaceQueryPolicy";

/** A pinned session, with the space it belongs to. */
export interface PinnedSpaceTask {
  item: ChannelItemModel;
  spaceId: string;
}

/**
 * Module-level so `useQueries` can memoize on it — an inline combine is a new
 * function every render, and every render would then rebuild the list.
 */
function combineTasks(queries: { data?: Task }[]): (Task | undefined)[] {
  return queries.map((query) => query.data);
}

const NO_PINS: PinnedSpaceTask[] = [];

/**
 * Every pinned session, newest first, across all spaces.
 *
 * One query per pin, sharing the task detail cache: a pin is a session you keep
 * going back to, so the row is usually warm before it is drawn, and opening one
 * costs no fetch. That beats both alternatives — the full task list is ~630KB a
 * poll, and the space feeds only cover spaces the tree has open.
 *
 * A pin outside the spaces (the Code app pins the same tasks) has nowhere to be
 * opened here, so it is left out rather than drawn as a row that can't route.
 */
export function usePinnedSpaceTasks(): PinnedSpaceTask[] {
  const { pinnedTaskIds } = usePinnedTasks();
  const archivedTaskIds = useArchivedTaskIds();
  // Sorted so the array only changes when the set of pins does.
  const ids = useMemo(() => [...pinnedTaskIds].sort(), [pinnedTaskIds]);

  const tasks = useQueries({
    queries: ids.map((id) => ({
      ...taskDetailQuery(id),
      staleTime: SPACE_QUERY_STALE_TIME_MS,
    })),
    combine: combineTasks,
  });

  return useMemo(() => {
    const loaded = tasks.filter((task): task is Task => task != null);
    if (loaded.length === 0) return NO_PINS;
    return buildChannelItems({
      dashboards: [],
      feedTasks: loaded,
      archivedTaskIds,
      pinnedTaskIds,
      ownedBy: null,
    }).flatMap((item) =>
      item.task?.channel
        ? [{ item, spaceId: item.task.channel }]
        : // A pin whose task the API no longer places in a space.
          [],
    );
  }, [tasks, archivedTaskIds, pinnedTaskIds]);
}
