import { create } from "zustand";

/**
 * Per-task counter that forces useSessionConnection's reconcile effect to
 * re-run. The manual resync action bumps it after stopping the cloud watch,
 * so the effect rebuilds the watcher — subscription, main-process watch, and
 * snapshot replay — from scratch: the same recovery an app reload performs,
 * scoped to one task.
 */
interface SessionResyncState {
  nonces: Record<string, number>;
  bump: (taskId: string) => void;
}

export const useSessionResyncStore = create<SessionResyncState>()((set) => ({
  nonces: {},
  bump: (taskId) =>
    set((state) => ({
      nonces: { ...state.nonces, [taskId]: (state.nonces[taskId] ?? 0) + 1 },
    })),
}));
