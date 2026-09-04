import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface TaskFeed {
  id: string;
  projectId: number;
  ownerId: string;
  name: string;
  query: string;
  createdAt: string;
}

interface TaskFeedsState {
  feeds: TaskFeed[];
  hasHydrated: boolean;
  setHasHydrated: (hydrated: boolean) => void;
  addFeed: (input: {
    name: string;
    query: string;
    projectId: number;
    ownerId: string;
  }) => TaskFeed;
  updateFeed: (id: string, patch: { name?: string; query?: string }) => void;
  removeFeed: (id: string) => void;
}

// Feeds are personal and project-scoped, so callers must use `useProjectTaskFeeds`.
export const useTaskFeedsStore = create<TaskFeedsState>()(
  persist(
    (set) => ({
      feeds: [],
      hasHydrated: false,
      setHasHydrated: (hydrated) => set({ hasHydrated: hydrated }),
      addFeed: ({ name, query, projectId, ownerId }) => {
        const feed: TaskFeed = {
          id: crypto.randomUUID(),
          projectId,
          ownerId,
          name: name.trim(),
          query: query.trim(),
          createdAt: new Date().toISOString(),
        };
        set((state) => ({ feeds: [...state.feeds, feed] }));
        return feed;
      },
      updateFeed: (id, patch) =>
        set((state) => ({
          feeds: state.feeds.map((feed) =>
            feed.id === id
              ? {
                  ...feed,
                  ...(patch.name !== undefined
                    ? { name: patch.name.trim() }
                    : {}),
                  ...(patch.query !== undefined
                    ? { query: patch.query.trim() }
                    : {}),
                }
              : feed,
          ),
        })),
      removeFeed: (id) =>
        set((state) => ({
          feeds: state.feeds.filter((feed) => feed.id !== id),
        })),
    }),
    {
      name: "task-feeds-storage",
      storage: electronStorage,
      partialize: ({ feeds }) => ({ feeds }),
      onRehydrateStorage: () => (state, error) => {
        if (error) {
          useTaskFeedsStore.getState().setHasHydrated(true);
        } else {
          state?.setHasHydrated(true);
        }
      },
    },
  ),
);

export function ownedProjectFeeds(
  feeds: readonly TaskFeed[],
  projectId: number | null,
  ownerId: string | undefined,
): TaskFeed[] {
  if (projectId === null || ownerId === undefined) return [];
  return feeds.filter(
    (feed) => feed.projectId === projectId && feed.ownerId === ownerId,
  );
}
