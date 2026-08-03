import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

// Tracks whether the "Before you head to PostHog web" feedback intercept has
// already run once. After the user submits, skips, or dismisses it, going back
// to PostHog web navigates straight there instead of prompting again.
interface PostHogWebFeedbackState {
  hasSeen: boolean;
  // Storage is read asynchronously (Electron IPC); hasSeen exposes its default
  // until the read settles. Readers can gate on this to avoid trusting the
  // pre-hydration default.
  hasHydrated: boolean;
  markSeen: () => void;
  setHasHydrated: (hydrated: boolean) => void;
}

export const usePostHogWebFeedbackStore = create<PostHogWebFeedbackState>()(
  persist(
    (set) => ({
      hasSeen: false,
      hasHydrated: false,
      markSeen: () => set({ hasSeen: true }),
      setHasHydrated: (hydrated) => set({ hasHydrated: hydrated }),
    }),
    {
      name: "posthog-web-feedback-seen",
      storage: electronStorage,
      partialize: (state) => ({ hasSeen: state.hasSeen }),
      // A markSeen() that lands before the async read returns would otherwise be
      // undone by zustand's default merge overwriting it with the persisted
      // value. Keep hasSeen sticky so the one-time intercept is never re-shown.
      merge: (persisted, current) => ({
        ...current,
        hasSeen:
          current.hasSeen ||
          (persisted as Partial<PostHogWebFeedbackState>)?.hasSeen === true,
      }),
      onRehydrateStorage: () => (state) => {
        if (state) {
          state.setHasHydrated(true);
          return;
        }
        // Failed read: fail open as unseen. Re-showing the intercept once beats
        // never navigating; the in-session markSeen still suppresses it after.
        usePostHogWebFeedbackStore.setState({ hasHydrated: true });
      },
    },
  ),
);
