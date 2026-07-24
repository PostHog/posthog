import AsyncStorage from "@react-native-async-storage/async-storage";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

interface DismissedReportsState {
  /** Report IDs swiped left (dismissed). */
  dismissedIds: string[];
  /** Report IDs swiped right (accepted / task started). */
  acceptedIds: string[];
}

interface DismissedReportsActions {
  dismissReport: (reportId: string) => void;
  acceptReport: (reportId: string) => void;
  undismissReport: (reportId: string) => void;
  clearDismissed: () => void;
}

type DismissedReportsStore = DismissedReportsState & DismissedReportsActions;

/** All report IDs the user has acted on (swiped left or right). */
export function decidedIds(state: DismissedReportsState): string[] {
  return [...state.dismissedIds, ...state.acceptedIds];
}

export const useDismissedReportsStore = create<DismissedReportsStore>()(
  persist(
    (set) => ({
      dismissedIds: [],
      acceptedIds: [],
      dismissReport: (reportId) =>
        set((state) => ({
          dismissedIds: state.dismissedIds.includes(reportId)
            ? state.dismissedIds
            : [...state.dismissedIds, reportId],
        })),
      acceptReport: (reportId) =>
        set((state) => ({
          acceptedIds: state.acceptedIds.includes(reportId)
            ? state.acceptedIds
            : [...state.acceptedIds, reportId],
        })),
      undismissReport: (reportId) =>
        set((state) => ({
          dismissedIds: state.dismissedIds.filter((id) => id !== reportId),
          acceptedIds: state.acceptedIds.filter((id) => id !== reportId),
        })),
      clearDismissed: () => set({ dismissedIds: [], acceptedIds: [] }),
    }),
    {
      name: "dismissed-reports-storage",
      storage: createJSONStorage(() => AsyncStorage),
      partialize: (state) => ({
        dismissedIds: state.dismissedIds,
        acceptedIds: state.acceptedIds,
      }),
    },
  ),
);
