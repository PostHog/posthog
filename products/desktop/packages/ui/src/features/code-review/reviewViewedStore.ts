import { create } from "zustand";
import { persist } from "zustand/middleware";

interface ReviewViewedStoreState {
  viewed: Record<string, Record<string, string>>;
}

interface ReviewViewedStoreActions {
  setViewed: (taskId: string, key: string, sig: string | null) => void;
  clearTasks: (taskIds: Iterable<string>) => void;
}

type ReviewViewedStore = ReviewViewedStoreState & ReviewViewedStoreActions;

export const useReviewViewedStore = create<ReviewViewedStore>()(
  persist(
    (set) => ({
      viewed: {},
      setViewed: (taskId, key, sig) =>
        set((state) => {
          const taskViewed = { ...(state.viewed[taskId] ?? {}) };
          if (sig === null) delete taskViewed[key];
          else taskViewed[key] = sig;
          const next = { ...state.viewed };
          if (Object.keys(taskViewed).length > 0) next[taskId] = taskViewed;
          else delete next[taskId];
          return { viewed: next };
        }),
      clearTasks: (taskIds) =>
        set((state) => {
          let changed = false;
          const next = { ...state.viewed };
          for (const id of taskIds) {
            if (id in next) {
              delete next[id];
              changed = true;
            }
          }
          return changed ? { viewed: next } : state;
        }),
    }),
    {
      name: "review-viewed-storage",
      version: 1,
      migrate: (persisted, version) => {
        if (version < 1) return { viewed: {} };
        return persisted as ReviewViewedStoreState;
      },
    },
  ),
);
