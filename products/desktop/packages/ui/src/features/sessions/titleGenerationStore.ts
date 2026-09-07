import { create } from "zustand";

// Shared across all mounted chat views of a task (refs would reset on every
// mount, re-firing LLM title generation per view switch). In-memory only.
export interface TitleGenerationEntry {
  lastGeneratedAtCount: number;
  initialDescriptionHandled: boolean;
  inFlight: boolean;
}

const EMPTY_ENTRY: TitleGenerationEntry = {
  lastGeneratedAtCount: 0,
  initialDescriptionHandled: false,
  inFlight: false,
};

interface TitleGenerationStore {
  byTaskId: Record<string, TitleGenerationEntry>;
  update: (taskId: string, patch: Partial<TitleGenerationEntry>) => void;
}

export const useTitleGenerationStore = create<TitleGenerationStore>((set) => ({
  byTaskId: {},
  update: (taskId, patch) =>
    set((state) => ({
      byTaskId: {
        ...state.byTaskId,
        [taskId]: { ...(state.byTaskId[taskId] ?? EMPTY_ENTRY), ...patch },
      },
    })),
}));

export const titleGenerationStoreApi = {
  get: (taskId: string): TitleGenerationEntry =>
    useTitleGenerationStore.getState().byTaskId[taskId] ?? EMPTY_ENTRY,
  update: (taskId: string, patch: Partial<TitleGenerationEntry>) =>
    useTitleGenerationStore.getState().update(taskId, patch),
};
