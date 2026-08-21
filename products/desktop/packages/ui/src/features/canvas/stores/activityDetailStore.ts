import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { create } from "zustand";

interface ActivityDetailState {
  /**
   * The feed row being read in the pane beside it. Held here rather than in the
   * URL: picking a row is browsing the feed, and routing away from Activity
   * would take the feed off the screen you are reading it from.
   */
  selected: TaskActivityItem | null;
  select: (item: TaskActivityItem | null) => void;
}

export const useActivityDetailStore = create<ActivityDetailState>()((set) => ({
  selected: null,
  select: (selected) => set({ selected }),
}));
