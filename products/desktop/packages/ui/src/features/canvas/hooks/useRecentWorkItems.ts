import {
  buildChannelItems,
  type ChannelItemModel,
} from "@posthog/core/canvas/channelItems";
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

  const items = useMemo<RecentWorkItem[]>(() => {
    const mine = dashboards.filter(
      (canvas) =>
        lastViewedByCanvasId[canvas.id] != null ||
        (meUuid != null && canvas.createdByUuid === meUuid),
    );
    const channelByKey = new Map<string, string | undefined>();
    for (const canvas of mine)
      channelByKey.set(`canvas:${canvas.id}`, canvas.channelId);
    for (const task of tasks) {
      channelByKey.set(`task:${task.id}`, task.channel ?? undefined);
    }
    const built = buildChannelItems({
      dashboards: mine,
      feedTasks: tasks,
      archivedTaskIds,
      pinnedTaskIds,
      ownedBy: null,
      sessionFacts,
    });
    return built
      .map((item) => {
        const viewedAt =
          item.kind === "canvas"
            ? (lastViewedByCanvasId[item.id] ?? 0)
            : (sessionFacts.viewedTimestamps[item.id]?.lastViewedAt ?? 0);
        return { item: { ...item, ts: Math.max(item.ts, viewedAt) } };
      })
      .sort((a, b) => b.item.ts - a.item.ts)
      .slice(0, RECENT_WORK_CAP)
      .map(({ item }) => ({ item, channelId: channelByKey.get(item.key) }));
  }, [
    dashboards,
    lastViewedByCanvasId,
    meUuid,
    tasks,
    archivedTaskIds,
    pinnedTaskIds,
    sessionFacts,
  ]);

  return { items, isLoading: tasksLoading || canvasesLoading };
}
