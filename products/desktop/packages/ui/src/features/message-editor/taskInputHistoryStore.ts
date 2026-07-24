import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface TaskInputHistoryEntry {
  text: string;
  createdAt: number | null;
}

interface TaskInputHistoryState {
  entries: TaskInputHistoryEntry[];
}

interface TaskInputHistoryActions {
  addPrompt: (prompt: string) => void;
}

type TaskInputHistoryStore = TaskInputHistoryState & TaskInputHistoryActions;

const MAX_HISTORY = 15;

export const useTaskInputHistoryStore = create<TaskInputHistoryStore>()(
  persist(
    (set) => ({
      entries: [],
      addPrompt: (prompt) =>
        set((state) => {
          const trimmed = prompt.trim();
          if (!trimmed) return state;
          const filtered = state.entries.filter((e) => e.text !== trimmed);
          const updated = [
            ...filtered,
            { text: trimmed, createdAt: Date.now() },
          ].slice(-MAX_HISTORY);
          return { entries: updated };
        }),
    }),
    {
      name: "task-input-history",
      version: 1,
      partialize: (state) => ({ entries: state.entries }),
      // v0 → v1: convert the flat `prompts: string[]` list into the new
      // `entries: { text, createdAt }[]` shape. Old prompts predate
      // timestamps so `createdAt` is null — the dialog omits the
      // relative-time row when it's missing.
      migrate: (persisted, version) => {
        if (version === 0 && persisted && typeof persisted === "object") {
          const old = persisted as { prompts?: unknown };
          if (Array.isArray(old.prompts)) {
            return {
              entries: old.prompts
                .filter((p): p is string => typeof p === "string")
                .map((text) => ({ text, createdAt: null })),
            };
          }
        }
        return persisted as TaskInputHistoryState;
      },
    },
  ),
);
