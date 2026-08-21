import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { create } from "zustand";

export interface ActivitySelection {
  id: string;
  taskId: string;
  channelId: string | null;
}

interface ActivityDetailState {
  /** Held here rather than in the URL: routing away from Activity would take
   *  the feed off the screen you are reading it from. */
  selected: ActivitySelection | null;
  select: (selection: ActivitySelection | null) => void;
}

export const useActivityDetailStore = create<ActivityDetailState>()((set) => ({
  selected: null,
  select: (selected) => set({ selected }),
}));

export function selectActivityItem(item: TaskActivityItem): void {
  useActivityDetailStore.getState().select({
    id: item.id,
    taskId: item.taskId,
    channelId: item.channelId,
  });
}
