import type { DismissalReasonOptionValue } from "@posthog/shared";
import { create } from "zustand";

export interface DismissDraft {
  reason: DismissalReasonOptionValue;
  note: string;
  reopen: boolean;
  errorMessage?: string;
}

interface DismissDraftState {
  drafts: Record<string, DismissDraft | undefined>;
  setDraft: (reportId: string, draft: DismissDraft | undefined) => void;
}

export const useDismissDraftStore = create<DismissDraftState>((set) => ({
  drafts: {},
  setDraft: (reportId, draft) =>
    set((state) => {
      const next = { ...state.drafts };
      if (draft === undefined) {
        delete next[reportId];
      } else {
        next[reportId] = draft;
      }
      return { drafts: next };
    }),
}));
