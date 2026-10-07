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
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useMemo } from "react";

export const RECENT_WORK_CAP = 50;

export interface RecentWorkItem {
  item: ChannelItemModel;
  channelId: string | undefined;
}

export function selectRecentWorkItems({
  dashboards,
  tasks,
  lastViewedByCanvasId,
  meUuid,
  archivedTaskIds,
  pinnedTaskIds,
  sessionFacts,
}: {
  dashboards: readonly DashboardRecord[];
  tasks: readonly Task[];
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
  // The order is the items' own activity time. Opening an item is not activity,
  // so the local "viewed" time stays out of it and only says which canvases
  // belong to this list.
  return buildChannelItems({
    dashboards: mine,
    feedTasks: tasks,
    archivedTaskIds,
    pinnedTaskIds,
    ownedBy: null,
    sessionFacts,
  })
    .sort((a, b) => b.ts - a.ts)
    .filter(
      (item, index) =>
        index < RECENT_WORK_CAP || (item.kind === "task" && item.pinned),
    )
    .map((item) => ({
      item,
      channelId: item.task?.channel ?? canvasChannelId.get(item.id),
    }));
}

export function useRecentWorkItems(): {
  items: RecentWorkItem[];
  isLoading: boolean;
} {
  const { data: tasks = [], isLoading: tasksLoading } = useTasks();
  const { dashboards, isLoading: canvasesLoading } = useAllCanvases();
  const lastViewedByCanvasId = useCanvasViewedStore(
    (state) => state.lastViewedAtByCanvasId,
  );
  const archivedTaskIds = useArchivedTaskIds();
  const { pinnedTaskIds } = usePinnedTasks();
  const sessionFacts = useChannelSessionFacts();
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });
  const meUuid = currentUser?.uuid ?? null;

  const items = useMemo<RecentWorkItem[]>(
    () =>
      selectRecentWorkItems({
        dashboards,
        tasks,
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
      archivedTaskIds,
      pinnedTaskIds,
      sessionFacts,
    ],
  );

  return { items, isLoading: tasksLoading || canvasesLoading };
}
