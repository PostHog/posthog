import { create } from "zustand";
import type { SignalReportOrderingField } from "../types";

type OrderDirection = "asc" | "desc";

/** Set of report IDs the user has swiped past (skipped) this session. */
type SkippedSet = Set<string>;

interface InboxStoreState {
  /** Field used for API ordering */
  orderByField: SignalReportOrderingField;
  /** Sort direction */
  orderDirection: OrderDirection;
  /** Report IDs skipped (swiped left) during this session */
  skippedIds: SkippedSet;
  /** Index of the currently visible card in the deck */
  currentIndex: number;
  /**
   * Snapshot of the report IDs visible in the last-rendered list view, used
   * for analytics (rank + list_size) when a detail screen is opened by tapping
   * a list row.
   */
  lastVisibleReportIds: string[];
  /** Most recently opened report ID, used for `previous_report_id` on OPENED events. */
  previousOpenedReportId: string | null;
}

interface InboxStoreActions {
  setOrderByField: (field: SignalReportOrderingField) => void;
  setOrderDirection: (direction: OrderDirection) => void;
  skipReport: (reportId: string) => void;
  resetSkipped: () => void;
  setCurrentIndex: (index: number) => void;
  advanceCard: () => void;
  setLastVisibleReportIds: (ids: string[]) => void;
  setPreviousOpenedReportId: (id: string | null) => void;
}

type InboxStore = InboxStoreState & InboxStoreActions;

export const useInboxStore = create<InboxStore>((set) => ({
  orderByField: "priority",
  orderDirection: "desc",
  skippedIds: new Set(),
  currentIndex: 0,
  lastVisibleReportIds: [],
  previousOpenedReportId: null,

  setOrderByField: (orderByField) => set({ orderByField }),
  setOrderDirection: (orderDirection) => set({ orderDirection }),
  skipReport: (reportId) =>
    set((state) => {
      const next = new Set(state.skippedIds);
      next.add(reportId);
      return { skippedIds: next };
    }),
  resetSkipped: () => set({ skippedIds: new Set(), currentIndex: 0 }),
  setCurrentIndex: (currentIndex) => set({ currentIndex }),
  advanceCard: () => set((state) => ({ currentIndex: state.currentIndex + 1 })),
  setLastVisibleReportIds: (lastVisibleReportIds) =>
    set({ lastVisibleReportIds }),
  setPreviousOpenedReportId: (previousOpenedReportId) =>
    set({ previousOpenedReportId }),
}));
