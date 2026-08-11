import {
  electronStorage,
  flushRendererStateWrites,
} from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface AnnouncementsState {
  dismissedIds: Record<string, true>;
  // One announcement per app session: dismissing or acknowledging anything
  // parks the remaining announcements until the next launch. In-memory only —
  // partialize keeps it out of storage so a relaunch resets it.
  handledThisSession: boolean;
  // Hydration is async (Electron storage over IPC); announcements must not
  // flash for users whose persisted dismissals haven't been read back yet.
  _hasHydrated: boolean;
  dismiss: (id: string) => void;
  undismiss: (id: string) => void;
  setHasHydrated: (hydrated: boolean) => void;
}

export const useAnnouncementsStore = create<AnnouncementsState>()(
  persist(
    (set) => ({
      dismissedIds: {},
      handledThisSession: false,
      _hasHydrated: false,
      // Flushed immediately: the debounced write could otherwise be lost if
      // the window closes right after the click, resurrecting the announcement.
      dismiss: (id) => {
        set((state) => ({
          dismissedIds: { ...state.dismissedIds, [id]: true },
          handledThisSession: true,
        }));
        void flushRendererStateWrites();
      },
      // Reverts a dismissal committed at the update handoff when the install
      // fails before the app quits — the blocking announcement must come
      // back, this session included.
      undismiss: (id) => {
        set((state) => {
          const dismissedIds = { ...state.dismissedIds };
          delete dismissedIds[id];
          return { dismissedIds, handledThisSession: false };
        });
        void flushRendererStateWrites();
      },
      setHasHydrated: (hydrated) => set({ _hasHydrated: hydrated }),
    }),
    {
      name: "posthog-desktop-announcements-dismissed",
      storage: electronStorage,
      partialize: (state) => ({ dismissedIds: state.dismissedIds }),
      onRehydrateStorage: () => (state) => {
        if (state) {
          state.setHasHydrated(true);
          return;
        }
        useAnnouncementsStore.setState({ _hasHydrated: true });
      },
    },
  ),
);
