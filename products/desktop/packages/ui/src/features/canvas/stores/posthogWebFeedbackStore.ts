import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

// Tracks whether the "Before you head to PostHog web" feedback intercept has
// already run once. After the user submits, skips, or dismisses it, going back
// to PostHog web navigates straight there instead of prompting again.
interface PostHogWebFeedbackState {
  hasSeen: boolean;
  markSeen: () => void;
}

export const usePostHogWebFeedbackStore = create<PostHogWebFeedbackState>()(
  persist(
    (set) => ({
      hasSeen: false,
      markSeen: () => set({ hasSeen: true }),
    }),
    {
      name: "posthog-web-feedback-seen",
      storage: electronStorage,
      partialize: (state) => ({ hasSeen: state.hasSeen }),
    },
  ),
);
