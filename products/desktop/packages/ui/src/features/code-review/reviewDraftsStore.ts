import type { DraftComment } from "@posthog/core/code-review/types";
import { create } from "zustand";

export type { DraftComment } from "@posthog/core/code-review/types";

interface ReviewDraftsStoreState {
  drafts: Record<string, DraftComment[]>;
  batchEnabled: Record<string, boolean>;
}

interface ReviewDraftsStoreActions {
  addDraft: (
    taskId: string,
    draft: Omit<DraftComment, "id" | "taskId" | "createdAt">,
  ) => string;
  updateDraft: (taskId: string, draftId: string, text: string) => void;
  removeDraft: (taskId: string, draftId: string) => void;
  clearDrafts: (taskId: string) => void;
  setBatchEnabled: (taskId: string, value: boolean) => void;
  getDrafts: (taskId: string) => DraftComment[];
  getDraftsForFile: (taskId: string, filePath: string) => DraftComment[];
  getDraftCount: (taskId: string) => number;
  isBatchEnabled: (taskId: string) => boolean;
}

type ReviewDraftsStore = ReviewDraftsStoreState & ReviewDraftsStoreActions;

export const useReviewDraftsStore = create<ReviewDraftsStore>()((set, get) => ({
  drafts: {},
  batchEnabled: {},

  addDraft: (taskId, draft) => {
    const id = crypto.randomUUID();
    set((state) => {
      const existing = state.drafts[taskId] ?? [];
      const next: DraftComment = {
        id,
        taskId,
        createdAt: Date.now(),
        ...draft,
      };
      return {
        drafts: { ...state.drafts, [taskId]: [...existing, next] },
      };
    });
    return id;
  },

  updateDraft: (taskId, draftId, text) =>
    set((state) => {
      const existing = state.drafts[taskId];
      if (!existing) return state;
      return {
        drafts: {
          ...state.drafts,
          [taskId]: existing.map((d) =>
            d.id === draftId ? { ...d, text } : d,
          ),
        },
      };
    }),

  removeDraft: (taskId, draftId) =>
    set((state) => {
      const existing = state.drafts[taskId];
      if (!existing) return state;
      return {
        drafts: {
          ...state.drafts,
          [taskId]: existing.filter((d) => d.id !== draftId),
        },
      };
    }),

  clearDrafts: (taskId) =>
    set((state) => {
      if (!(taskId in state.drafts) && !(taskId in state.batchEnabled)) {
        return state;
      }
      const nextDrafts = { ...state.drafts };
      delete nextDrafts[taskId];
      const nextBatch = { ...state.batchEnabled };
      delete nextBatch[taskId];
      return { drafts: nextDrafts, batchEnabled: nextBatch };
    }),

  setBatchEnabled: (taskId, value) =>
    set((state) => ({
      batchEnabled: { ...state.batchEnabled, [taskId]: value },
    })),

  getDrafts: (taskId) => get().drafts[taskId] ?? [],
  getDraftsForFile: (taskId, filePath) =>
    (get().drafts[taskId] ?? []).filter((d) => d.filePath === filePath),
  getDraftCount: (taskId) => (get().drafts[taskId] ?? []).length,
  isBatchEnabled: (taskId) => {
    const state = get();
    if (taskId in state.batchEnabled) return state.batchEnabled[taskId];
    return (state.drafts[taskId]?.length ?? 0) > 0;
  },
}));
