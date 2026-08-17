import type { AutoresearchDraftConfig } from "@posthog/core/autoresearch/schemas";
import { create } from "zustand";

/**
 * Autoresearch mode armed on a new task composer, keyed by the composer
 * draft session id. Submitting the composer turns the draft into a run.
 */
interface AutoresearchDraftState {
  drafts: Record<string, AutoresearchDraftConfig>;
  setDraft: (sessionId: string, draft: AutoresearchDraftConfig) => void;
  updateDraft: (
    sessionId: string,
    patch: Partial<AutoresearchDraftConfig>,
  ) => void;
  clearDraft: (sessionId: string) => void;
}

export const useAutoresearchDraftStore = create<AutoresearchDraftState>(
  (set) => ({
    drafts: {},
    setDraft: (sessionId, draft) =>
      set((state) => ({ drafts: { ...state.drafts, [sessionId]: draft } })),
    updateDraft: (sessionId, patch) =>
      set((state) => {
        const draft = state.drafts[sessionId];
        if (!draft) return state;
        return {
          drafts: { ...state.drafts, [sessionId]: { ...draft, ...patch } },
        };
      }),
    clearDraft: (sessionId) =>
      set((state) => {
        const drafts = { ...state.drafts };
        delete drafts[sessionId];
        return { drafts };
      }),
  }),
);

export type PendingAutoresearchRun = AutoresearchDraftConfig & {
  instructions: string;
};

/**
 * Single-slot handoff of the run config between composer submission and the
 * task-created callback (which learns the new task's id). Only one task
 * creation is in flight at a time, so one slot suffices.
 */
let pendingRun: PendingAutoresearchRun | null = null;

export const autoresearchPendingRun = {
  set(config: PendingAutoresearchRun): void {
    pendingRun = config;
  },
  consume(): PendingAutoresearchRun | null {
    const config = pendingRun;
    pendingRun = null;
    return config;
  },
  clear(): void {
    pendingRun = null;
  },
};
