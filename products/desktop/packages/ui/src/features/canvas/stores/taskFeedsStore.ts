import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * A custom feed: a saved task query rendered with the channel feed's cards.
 * It is a saved question ("my failing CI tasks", "everything about billing"),
 * not a materialized list — the query runs each time the feed is opened, so
 * new matches appear without any per-feed bookkeeping.
 */
export interface TaskFeed {
  id: string;
  projectId: number;
  name: string;
  /** Free-text task query, run against the tasks list search filter. */
  query: string;
  createdAt: string;
}

interface TaskFeedsState {
  feeds: TaskFeed[];
  addFeed: (input: {
    name: string;
    query: string;
    projectId: number;
  }) => TaskFeed;
  updateFeed: (id: string, patch: { name?: string; query?: string }) => void;
  removeFeed: (id: string) => void;
}

// Per-device on purpose for the first cut: a feed is a personal saved view,
// like the sidebar's collapsed sections. Team-shared feeds need a backend
// model and visibility rules, which this store deliberately doesn't fake.
// Every feed carries the project it was saved in: read it through
// `useProjectTaskFeeds`, never `feeds` directly, or searches cross projects.
export const useTaskFeedsStore = create<TaskFeedsState>()(
  persist(
    (set) => ({
      feeds: [],
      addFeed: ({ name, query, projectId }) => {
        const feed: TaskFeed = {
          id: crypto.randomUUID(),
          projectId,
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
    },
  ),
);
