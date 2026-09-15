import { create } from "zustand";

export type FeedbackModalMode = "feedback" | "posthog-web";

interface FeedbackState {
  mode: FeedbackModalMode | null;
  onFinished: (() => void) | null;
  open: (mode?: FeedbackModalMode, onFinished?: () => void) => void;
  finish: () => void;
}

export const useFeedbackStore = create<FeedbackState>((set, get) => ({
  mode: null,
  onFinished: null,
  open: (mode = "feedback", onFinished) =>
    set((state) =>
      state.mode ? state : { mode, onFinished: onFinished ?? null },
    ),
  finish: () => {
    const onFinished = get().onFinished;
    set({ mode: null, onFinished: null });
    onFinished?.();
  },
}));
