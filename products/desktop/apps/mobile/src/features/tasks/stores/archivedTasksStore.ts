import AsyncStorage from "@react-native-async-storage/async-storage";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

// Cap on how many archived task IDs we persist. Beyond this, the oldest
// entries are evicted so AsyncStorage doesn't grow without bound.
const MAX_ARCHIVED_TASKS = 100;

interface ArchivedTasksState {
  // taskId → timestamp (ms) for eviction ordering
  archivedTasks: Record<string, number>;
  archive: (taskId: string) => void;
  archiveMany: (taskIds: string[]) => void;
  unarchive: (taskId: string) => void;
  isArchived: (taskId: string) => boolean;
}

function withCap(entries: Record<string, number>): Record<string, number> {
  const ids = Object.keys(entries);
  if (ids.length <= MAX_ARCHIVED_TASKS) return entries;
  const kept = ids
    .sort((a, b) => entries[b] - entries[a])
    .slice(0, MAX_ARCHIVED_TASKS);
  const trimmed: Record<string, number> = {};
  for (const id of kept) trimmed[id] = entries[id];
  return trimmed;
}

export const useArchivedTasksStore = create<ArchivedTasksState>()(
  persist(
    (set, get) => ({
      archivedTasks: {},

      archive: (taskId: string) =>
        set((state) => ({
          archivedTasks: withCap({
            ...state.archivedTasks,
            [taskId]: Date.now(),
          }),
        })),

      archiveMany: (taskIds: string[]) =>
        set((state) => {
          if (taskIds.length === 0) return state;
          const now = Date.now();
          const next = { ...state.archivedTasks };
          for (const id of taskIds) next[id] = now;
          return { archivedTasks: withCap(next) };
        }),

      unarchive: (taskId: string) =>
        set((state) => {
          const { [taskId]: _, ...rest } = state.archivedTasks;
          return { archivedTasks: rest };
        }),

      isArchived: (taskId: string) => taskId in get().archivedTasks,
    }),
    {
      name: "archived-tasks",
      storage: createJSONStorage(() => AsyncStorage),
      partialize: (state) => ({ archivedTasks: state.archivedTasks }),
    },
  ),
);
