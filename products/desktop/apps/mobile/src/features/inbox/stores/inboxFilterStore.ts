import { INBOX_PIPELINE_STATUSES } from "@posthog/core/inbox/reportFiltering";
import type { SourceProduct } from "@posthog/shared";
import type {
  SignalReportOrderingField,
  SignalReportPriority,
  SignalReportStatus,
} from "@posthog/shared/domain-types";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

type SortField = Extract<
  SignalReportOrderingField,
  "priority" | "created_at" | "total_weight"
>;

type SortDirection = "asc" | "desc";

interface InboxFilterState {
  sortField: SortField;
  sortDirection: SortDirection;
  statusFilter: SignalReportStatus[];
  sourceProductFilter: SourceProduct[];
  suggestedReviewerFilter: string[];
  priorityFilter: SignalReportPriority[];
}

interface InboxFilterActions {
  setSort: (field: SortField, direction: SortDirection) => void;
  setStatusFilter: (statuses: SignalReportStatus[]) => void;
  toggleStatus: (status: SignalReportStatus) => void;
  toggleSourceProduct: (source: SourceProduct) => void;
  clearSourceProductFilter: () => void;
  toggleSuggestedReviewer: (reviewerUuid: string) => void;
  setSuggestedReviewerFilter: (reviewerUuids: string[]) => void;
  togglePriority: (priority: SignalReportPriority) => void;
  setPriorityFilter: (priorities: SignalReportPriority[]) => void;
  resetFilters: () => void;
}

type InboxFilterStore = InboxFilterState & InboxFilterActions;

export const useInboxFilterStore = create<InboxFilterStore>()(
  persist(
    (set) => ({
      sortField: "priority",
      sortDirection: "asc",
      statusFilter: [...INBOX_PIPELINE_STATUSES],
      sourceProductFilter: [],
      suggestedReviewerFilter: [],
      priorityFilter: [],

      setSort: (sortField, sortDirection) => set({ sortField, sortDirection }),
      setStatusFilter: (statusFilter) => set({ statusFilter }),
      toggleStatus: (status) =>
        set((state) => {
          const current = state.statusFilter;
          const next = current.includes(status)
            ? current.filter((s) => s !== status)
            : [...current, status];
          // Don't allow empty — keep at least one
          return { statusFilter: next.length > 0 ? next : current };
        }),
      toggleSourceProduct: (source) =>
        set((state) => {
          const current = state.sourceProductFilter;
          const next = current.includes(source)
            ? current.filter((s) => s !== source)
            : [...current, source];
          return { sourceProductFilter: next };
        }),
      clearSourceProductFilter: () => set({ sourceProductFilter: [] }),
      toggleSuggestedReviewer: (reviewerUuid) =>
        set((state) => {
          const current = state.suggestedReviewerFilter;
          const next = current.includes(reviewerUuid)
            ? current.filter((uuid) => uuid !== reviewerUuid)
            : [...current, reviewerUuid];
          return { suggestedReviewerFilter: next };
        }),
      setSuggestedReviewerFilter: (reviewerUuids) =>
        set({
          suggestedReviewerFilter: Array.from(new Set(reviewerUuids)),
        }),
      togglePriority: (priority) =>
        set((state) => {
          const current = state.priorityFilter;
          const next = current.includes(priority)
            ? current.filter((p) => p !== priority)
            : [...current, priority];
          return { priorityFilter: next };
        }),
      setPriorityFilter: (priorities) =>
        set({ priorityFilter: Array.from(new Set(priorities)) }),
      resetFilters: () =>
        set({
          statusFilter: [...INBOX_PIPELINE_STATUSES],
          sourceProductFilter: [],
          suggestedReviewerFilter: [],
          priorityFilter: [],
        }),
    }),
    {
      name: "inbox-filter-storage",
      storage: createJSONStorage(() => AsyncStorage),
      partialize: (state) => ({
        sortField: state.sortField,
        sortDirection: state.sortDirection,
        statusFilter: state.statusFilter,
        sourceProductFilter: state.sourceProductFilter,
        suggestedReviewerFilter: state.suggestedReviewerFilter,
        priorityFilter: state.priorityFilter,
      }),
    },
  ),
);
