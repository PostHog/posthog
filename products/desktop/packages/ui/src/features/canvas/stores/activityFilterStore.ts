import { create } from "zustand";
import { persist } from "zustand/middleware";

interface ActivityFilterStore {
  /** Show only activity that hasn't been read yet. */
  unreadsOnly: boolean;
  setUnreadsOnly: (unreadsOnly: boolean) => void;
}

// Per-device preference shared by the Activity popover and the Activity page, so
// the filter you set on one is the filter you find on the other.
export const useActivityFilterStore = create<ActivityFilterStore>()(
  persist(
    (set) => ({
      unreadsOnly: false,
      setUnreadsOnly: (unreadsOnly) => set({ unreadsOnly }),
    }),
    { name: "activity-filter-storage" },
  ),
);
