import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface InboxReportReadState {
  readByKey: Record<string, boolean>;
  hasHydrated: boolean;
  setRead: (key: string, read: boolean) => void;
}

export const useInboxReportReadStore = create<InboxReportReadState>()(
  persist(
    (set) => ({
      readByKey: {},
      hasHydrated: false,
      setRead: (key, read) =>
        set((state) =>
          state.readByKey[key] === read
            ? state
            : { readByKey: { ...state.readByKey, [key]: read } },
        ),
    }),
    {
      name: "inbox-report-read",
      storage: electronStorage,
      partialize: (state) => ({ readByKey: state.readByKey }),
      merge: (persisted, current) => ({
        ...current,
        readByKey: {
          ...(persisted as Partial<InboxReportReadState>)?.readByKey,
          ...current.readByKey,
        },
      }),
      onRehydrateStorage: () => () => {
        useInboxReportReadStore.setState({ hasHydrated: true });
      },
    },
  ),
);
