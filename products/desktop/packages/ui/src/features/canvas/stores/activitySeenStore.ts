import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

// When the viewer last opened the Activity page; mentions newer than this
// count toward the sidebar's unread badge.
interface ActivitySeenState {
  lastSeenAt: string | null;
  markSeen: () => void;
}

export const useActivitySeenStore = create<ActivitySeenState>()(
  persist(
    (set) => ({
      lastSeenAt: null,
      markSeen: () => set({ lastSeenAt: new Date().toISOString() }),
    }),
    {
      name: "channels-activity-seen",
      storage: electronStorage,
    },
  ),
);
