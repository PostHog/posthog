import { create } from "zustand";
import type { LoopFormValues } from "./loopFormTypes";

interface LoopDraftState {
  /**
   * One-shot values used to seed the create wizard when it's opened from the
   * landing prompt or a template. Consumed on the wizard's first render and
   * cleared, so the manual "New loop" button always starts from a blank form.
   */
  prefill: Partial<LoopFormValues> | null;
  setPrefill: (prefill: Partial<LoopFormValues> | null) => void;
}

export const useLoopDraftStore = create<LoopDraftState>((set) => ({
  prefill: null,
  setPrefill: (prefill) => set({ prefill }),
}));
