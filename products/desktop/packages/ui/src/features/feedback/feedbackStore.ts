import { create } from "zustand";

export type FeedbackModalMode = "feedback" | "posthog-web";

interface FeedbackState {
  mode: FeedbackModalMode | null;
  open: (mode?: FeedbackModalMode) => void;
  close: () => void;
}

export const useFeedbackStore = create<FeedbackState>((set) => ({
  mode: null,
  open: (mode = "feedback") => set({ mode }),
  close: () => set({ mode: null }),
}));
