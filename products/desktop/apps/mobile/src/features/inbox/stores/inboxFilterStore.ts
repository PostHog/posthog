import {
  INBOX_PIPELINE_STATUSES,
  type InboxCreatedWindow,
  type InboxSortDirection,
  type InboxSortField,
} from "@posthog/core/inbox/reportFiltering";
import type { SourceProduct } from "@posthog/shared";
import type {
  SignalReportPriority,
  SignalReportStatus,
} from "@posthog/shared/domain-types";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

interface InboxFilterState {
  /** Can hold a model sort the user can no longer use. Read the list sort through `useInboxActiveSort`. */
  sortField: InboxSortField;
  sortDirection: InboxSortDirection;
  /** Null means no created-in window. Read the list window through `useInboxActiveSort`. */
  createdWindow: InboxCreatedWindow | null;
  statusFilter: SignalReportStatus[];
  sourceProductFilter: SourceProduct[];
  suggestedReviewerFilter: string[];
  priorityFilter: SignalReportPriority[];
}

interface InboxFilterActions {
  setSort: (field: InboxSortField, direction: InboxSortDirection) => void;
  setCreatedWindow: (createdWindow: InboxCreatedWindow | null) => void;
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
      createdWindow: null,
      statusFilter: [...INBOX_PIPELINE_STATUSES],
      sourceProductFilter: [],
      suggestedReviewerFilter: [],
      priorityFilter: [],

      setSort: (sortField, sortDirection) => set({ sortField, sortDirection }),
      setCreatedWindow: (createdWindow) => set({ createdWindow }),
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
          createdWindow: null,
        }),
    }),
    {
      name: "inbox-filter-storage",
      storage: createJSONStorage(() => AsyncStorage),
      partialize: (state) => ({
        sortField: state.sortField,
        sortDirection: state.sortDirection,
        createdWindow: state.createdWindow,
        statusFilter: state.statusFilter,
        sourceProductFilter: state.sourceProductFilter,
        suggestedReviewerFilter: state.suggestedReviewerFilter,
        priorityFilter: state.priorityFilter,
      }),
    },
  ),
);
