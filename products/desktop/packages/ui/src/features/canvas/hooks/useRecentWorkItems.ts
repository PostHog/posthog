import { TASK_LIST_MAX_PAGE_SIZE } from "@posthog/api-client/posthog-client";
import {
  buildChannelItems,
  type ChannelItemModel,
  type ChannelSessionFacts,
} from "@posthog/core/canvas/channelItems";
import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import type { Task } from "@posthog/shared/domain-types";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useChannelSessionFacts } from "@posthog/ui/features/canvas/hooks/useChannelItems";
import { useAllCanvases } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useCanvasViewedStore } from "@posthog/ui/features/canvas/stores/canvasViewedStore";
import { usePinnedTasks } from "@posthog/ui/features/sidebar/usePinnedTasks";
import {
  usePinnedTaskRecords,
  useTasks,
} from "@posthog/ui/features/tasks/useTasks";
import { useMemo } from "react";

export const RECENT_WORK_CAP = 50;

export interface RecentWorkItem {
  item: ChannelItemModel;
  channelId: string | undefined;
}

// Pins always stay. The cap counts only the rest, so pins with newer activity cannot take the
// places of the recent work they sit beside.
function keepPinsAndCapRecent(
  items: readonly ChannelItemModel[],
): ChannelItemModel[] {
  let recent = 0;
  return items.filter(
    (item) =>
      (item.kind === "task" && item.pinned) || recent++ < RECENT_WORK_CAP,
  );
}

/**
 * The server cuts the page before pins are set apart, so the page leaves a row for each pin.
 * Otherwise the newest tasks could all be pins and leave Recent empty.
 */
export function recentWorkPageSize(pinCount: number): number {
  return Math.min(RECENT_WORK_CAP + pinCount, TASK_LIST_MAX_PAGE_SIZE);
}

export function selectRecentWorkItems({
  dashboards,
  tasks,
  pinnedTasks,
  lastViewedByCanvasId,
  meUuid,
  archivedTaskIds,
  pinnedTaskIds,
  sessionFacts,
}: {
  dashboards: readonly DashboardRecord[];
  tasks: readonly Task[];
  pinnedTasks: readonly Task[];
  lastViewedByCanvasId: Record<string, number>;
  meUuid: string | null;
  archivedTaskIds: ReadonlySet<string>;
  pinnedTaskIds: ReadonlySet<string>;
  sessionFacts: ChannelSessionFacts;
}): RecentWorkItem[] {
  const mine = dashboards.filter(
    (canvas) =>
      lastViewedByCanvasId[canvas.id] != null ||
      (meUuid != null && canvas.createdByUuid === meUuid),
  );
  const canvasChannelId = new Map(mine.map((c) => [c.id, c.channelId]));
  const taskIds = new Set(tasks.map((task) => task.id));
  // The order is the items' own activity time. Opening an item is not activity,
  // so the local "viewed" time stays out of it and only says which canvases
  // belong to this list.
  const items = buildChannelItems({
    dashboards: mine,
    feedTasks: [
      ...tasks,
      ...pinnedTasks.filter((task) => !taskIds.has(task.id)),
    ],
    archivedTaskIds,
    pinnedTaskIds,
    ownedBy: null,
    sessionFacts,
  }).sort((a, b) => b.ts - a.ts);
  return keepPinsAndCapRecent(items).map((item) => ({
    item,
    channelId: item.task?.channel ?? canvasChannelId.get(item.id),
  }));
}

export function useRecentWorkItems({
  sources,
}: {
  sources: readonly string[];
}): {
  items: RecentWorkItem[];
  isLoading: boolean;
} {
  const { pinnedTaskIds, isLoading: pinIdsLoading } = usePinnedTasks();
  // The server cuts the page from the newest activity: by creation date, a session started last
  // week and still in use is already off the page when scheduled runs create many tasks.
  const { data: tasks = [], isLoading: tasksLoading } = useTasks(
    {
      sources,
      limit: recentWorkPageSize(pinnedTaskIds.size),
      ordering: "-last_activity_at",
    },
    { keepPreviousPage: true },
  );
  const { data: pinnedTasks = [], isLoading: pinnedLoading } =
    usePinnedTaskRecords();
  const { dashboards, isLoading: canvasesLoading } = useAllCanvases();
  const lastViewedByCanvasId = useCanvasViewedStore(
    (state) => state.lastViewedAtByCanvasId,
  );
  const archivedTaskIds = useArchivedTaskIds();
  const sessionFacts = useChannelSessionFacts();
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });
  const meUuid = currentUser?.uuid ?? null;

  const items = useMemo<RecentWorkItem[]>(
    () =>
      selectRecentWorkItems({
        dashboards,
        tasks,
        pinnedTasks,
        lastViewedByCanvasId,
        meUuid,
        archivedTaskIds,
        pinnedTaskIds,
        sessionFacts,
      }),
    [
      dashboards,
      lastViewedByCanvasId,
      meUuid,
      tasks,
      pinnedTasks,
      archivedTaskIds,
      pinnedTaskIds,
      sessionFacts,
    ],
  );

  return {
    items,
    isLoading:
      tasksLoading || canvasesLoading || pinnedLoading || pinIdsLoading,
  };
}
