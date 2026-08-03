import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface BillingAnnouncementState {
  acknowledged: boolean;
  // Hydration is async (Electron storage over IPC); the announcement must not
  // flash open before a persisted acknowledgment has been read back.
  _hasHydrated: boolean;
  acknowledge: () => void;
  setHasHydrated: (hydrated: boolean) => void;
}

export const useBillingAnnouncementStore = create<BillingAnnouncementState>()(
  persist(
    (set) => ({
      acknowledged: false,
      _hasHydrated: false,
      acknowledge: () => set({ acknowledged: true }),
      setHasHydrated: (hydrated) => set({ _hasHydrated: hydrated }),
    }),
    {
      name: "posthog-code-usage-billing-acknowledged",
      storage: electronStorage,
      partialize: (state) => ({ acknowledged: state.acknowledged }),
      onRehydrateStorage: () => (state) => {
        if (state) {
          state.setHasHydrated(true);
          return;
        }
        // Failed storage read: fail open as unacknowledged — re-showing the
        // one-time announcement beats never showing it, and the in-memory
        // acknowledgment still dismisses it for the rest of the session.
        useBillingAnnouncementStore.setState({ _hasHydrated: true });
      },
    },
  ),
);
