import {
  DEFAULT_OBJECT_SORT,
  isObjectSort,
  type ObjectSort,
} from "@posthog/ui/features/command/objectSort";
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface ObjectSortState {
  sort: ObjectSort;
  setSort: (sort: ObjectSort) => void;
}

export const useObjectSortStore = create<ObjectSortState>()(
  persist(
    (set) => ({
      sort: DEFAULT_OBJECT_SORT,
      setSort: (sort) => set({ sort }),
    }),
    {
      name: "ph-command-menu-object-sort",
      partialize: (state) => ({ sort: state.sort }),
      merge: (persisted, current) => {
        const saved = (persisted as Partial<ObjectSortState> | undefined)?.sort;
        return { ...current, sort: isObjectSort(saved) ? saved : current.sort };
      },
    },
  ),
);
