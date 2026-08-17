import type {
  SignalReportOrderingField,
  SignalReportPriority,
  SourceProduct,
} from "@posthog/shared/types";
import { create } from "zustand";
import { persist } from "zustand/middleware";

export type { SourceProduct };

type SignalSortField = Extract<
  SignalReportOrderingField,
  "priority" | "created_at" | "total_weight"
>;

type SignalSortDirection = "asc" | "desc";

interface InboxSignalsFilterState {
  sortField: SignalSortField;
  sortDirection: SignalSortDirection;
  searchQuery: string;
  /** Empty array means "all sources" (no filter). */
  sourceProductFilter: SourceProduct[];
  /** Empty array means "all priorities" (no filter). */
  priorityFilter: SignalReportPriority[];
}

interface InboxSignalsFilterActions {
  setSort: (field: SignalSortField, direction: SignalSortDirection) => void;
  setSearchQuery: (query: string) => void;
  toggleSourceProduct: (source: SourceProduct) => void;
  togglePriority: (priority: SignalReportPriority) => void;
  setPriorityFilter: (priorities: SignalReportPriority[]) => void;
  /** Clear the source filter back to "Any" (empty = all sources). */
  clearSourceProductFilter: () => void;
  /** Reset all filters when a deep link arrives so the linked report isn't hidden. */
  resetFilters: () => void;
}

type InboxSignalsFilterStore = InboxSignalsFilterState &
  InboxSignalsFilterActions;

/**
 * v2 dropped per-status and per-reviewer filter UI; surviving consumers are sort,
 * search, source-product, and priority. Bumping the persist version drops the
 * old `statusFilter` / `suggestedReviewerFilter` / `hasInitializedSuggestedReviewerFilter`
 * keys from existing users' localStorage.
 */
export const useInboxSignalsFilterStore = create<InboxSignalsFilterStore>()(
  persist(
    (set) => ({
      sortField: "priority",
      sortDirection: "asc",
      searchQuery: "",
      sourceProductFilter: [],
      priorityFilter: [],
      setSort: (sortField, sortDirection) => set({ sortField, sortDirection }),
      setSearchQuery: (searchQuery) => set({ searchQuery }),
      toggleSourceProduct: (source) =>
        set((state) => {
          const current = state.sourceProductFilter;
          const next = current.includes(source)
            ? current.filter((s) => s !== source)
            : [...current, source];
          return { sourceProductFilter: next };
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
        set({
          priorityFilter: Array.from(new Set(priorities)),
        }),
      clearSourceProductFilter: () => set({ sourceProductFilter: [] }),
      resetFilters: () =>
        set({
          searchQuery: "",
          sourceProductFilter: [],
          priorityFilter: [],
        }),
    }),
    {
      name: "inbox-signals-filter-storage",
      version: 2,
      migrate: (persisted, version) => {
        if (version >= 2) return persisted;
        if (!persisted || typeof persisted !== "object") return persisted;
        const {
          statusFilter: _statusFilter,
          suggestedReviewerFilter: _suggestedReviewerFilter,
          hasInitializedSuggestedReviewerFilter:
            _hasInitializedSuggestedReviewerFilter,
          ...rest
        } = persisted as Record<string, unknown>;
        return rest;
      },
      partialize: (state) => ({
        sortField: state.sortField,
        sortDirection: state.sortDirection,
        sourceProductFilter: state.sourceProductFilter,
        priorityFilter: state.priorityFilter,
      }),
    },
  ),
);
