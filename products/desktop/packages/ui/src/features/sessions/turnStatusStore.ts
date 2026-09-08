import { create } from "zustand";

export interface TurnStatusEntry {
  requestKey: string | null;
  text: string | null;
}

const EMPTY_ENTRY: TurnStatusEntry = {
  requestKey: null,
  text: null,
};

interface TurnStatusStore {
  byTaskId: Record<string, TurnStatusEntry>;
  update: (taskId: string, patch: Partial<TurnStatusEntry>) => void;
}

export const useTurnStatusStore = create<TurnStatusStore>((set) => ({
  byTaskId: {},
  update: (taskId, patch) =>
    set((state) => ({
      byTaskId: {
        ...state.byTaskId,
        [taskId]: { ...(state.byTaskId[taskId] ?? EMPTY_ENTRY), ...patch },
      },
    })),
}));

export const turnStatusStoreApi = {
  get: (taskId: string): TurnStatusEntry =>
    useTurnStatusStore.getState().byTaskId[taskId] ?? EMPTY_ENTRY,
  update: (taskId: string, patch: Partial<TurnStatusEntry>): void =>
    useTurnStatusStore.getState().update(taskId, patch),
};

export function useTurnStatus(taskId: string | undefined): string | null {
  return useTurnStatusStore((state) =>
    taskId ? (state.byTaskId[taskId]?.text ?? null) : null,
  );
}
