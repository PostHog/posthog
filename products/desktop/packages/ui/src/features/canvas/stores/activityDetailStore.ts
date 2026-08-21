import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { create } from "zustand";

export interface ActivitySelection {
  /** The feed row, so the list can draw it as picked. */
  id: string;
  taskId: string;
  /** Backend channel id; null when the task is unfiled. */
  channelId: string | null;
}

interface ActivityDetailState {
  /**
   * The feed row being read in the pane beside it. Held here rather than in the
   * URL: picking a row is browsing the feed, and routing away from Activity
   * would take the feed off the screen you are reading it from.
   *
   * Narrowed to what the pane needs rather than the whole row — a stored copy
   * of a live feed row goes stale by construction, so the less of it kept the
   * better.
   */
  selected: ActivitySelection | null;
  select: (selection: ActivitySelection | null) => void;
}

export const useActivityDetailStore = create<ActivityDetailState>()((set) => ({
  selected: null,
  select: (selected) => set({ selected }),
}));

/** Read this row in the pane beside the feed. */
export function selectActivityItem(item: TaskActivityItem): void {
  useActivityDetailStore.getState().select({
    id: item.id,
    taskId: item.taskId,
    channelId: item.channelId,
  });
}
