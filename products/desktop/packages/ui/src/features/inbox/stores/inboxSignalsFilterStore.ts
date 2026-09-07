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

/** Whether to show every report, only PR-backed ones, or only PR-less ones. */
export type InboxPrFilter = "all" | "with_pr" | "without_pr";

export type InboxReportStateFilter =
  | "review_and_merge"
  | "needs_decision"
  | "resolved"
  | "dismissed";

export const DEFAULT_INBOX_REPORT_STATE_FILTER: InboxReportStateFilter[] = [
  "review_and_merge",
  "needs_decision",
];

interface InboxSignalsFilterState {
  sortField: SignalSortField;
  sortDirection: SignalSortDirection;
  searchQuery: string;
  /** Empty array means "all sources" (no filter). */
  sourceProductFilter: SourceProduct[];
  /** Empty array means "all priorities" (no filter). */
  priorityFilter: SignalReportPriority[];
  reportStateFilter: InboxReportStateFilter[];
  prFilter: InboxPrFilter;
}

interface InboxSignalsFilterActions {
  setSort: (field: SignalSortField, direction: SignalSortDirection) => void;
  setSearchQuery: (query: string) => void;
  toggleSourceProduct: (source: SourceProduct) => void;
  setSourceProductFilter: (sources: SourceProduct[]) => void;
  togglePriority: (priority: SignalReportPriority) => void;
  setPriorityFilter: (priorities: SignalReportPriority[]) => void;
  toggleReportState: (state: InboxReportStateFilter) => void;
  setReportStateFilter: (states: InboxReportStateFilter[]) => void;
  setPrFilter: (prFilter: InboxPrFilter) => void;
  /** Clear the source filter back to "Any" (empty = all sources). */
  clearSourceProductFilter: () => void;
  /** Reset all filters when a deep link arrives so the linked report isn't hidden. */
  resetFilters: () => void;
}

type InboxSignalsFilterStore = InboxSignalsFilterState &
  InboxSignalsFilterActions;

/**
 * Whether a filter that can hide reports is active. Sort only reorders the
 * list, so it does not count. This is the single definition of "filtered" used
 * by the empty states and the filter bar.
 *
 * Surfaces can exclude filters they do not expose, so a stored value they
 * ignore does not make their empty state read as "filtered".
 */
export function hasActiveInboxFilters(
  state: InboxSignalsFilterState,
  options?: {
    includePrFilter?: boolean;
    includeSourceFilter?: boolean;
    includeReportStateFilter?: boolean;
    includeSearchFilter?: boolean;
  },
): boolean {
  const includePrFilter = options?.includePrFilter ?? true;
  const includeSourceFilter = options?.includeSourceFilter ?? true;
  const includeReportStateFilter = options?.includeReportStateFilter ?? false;
  const includeSearchFilter = options?.includeSearchFilter ?? true;
  const stateFilterChanged =
    state.reportStateFilter.length !==
      DEFAULT_INBOX_REPORT_STATE_FILTER.length ||
    state.reportStateFilter.some(
      (value) => !DEFAULT_INBOX_REPORT_STATE_FILTER.includes(value),
    );
  return (
    (includeSearchFilter && state.searchQuery.trim().length > 0) ||
    (includeSourceFilter && state.sourceProductFilter.length > 0) ||
    state.priorityFilter.length > 0 ||
    (includeReportStateFilter && stateFilterChanged) ||
    (includePrFilter && state.prFilter !== "all")
  );
}

/**
 * v2 dropped per-status and per-reviewer filter UI; surviving consumers are sort,
 * search, source-product, and priority. Bumping the persist version drops the
 * old `statusFilter` / `suggestedReviewerFilter` / `hasInitializedSuggestedReviewerFilter`
 * keys from existing users' localStorage.
 */
export const useInboxSignalsFilterStore = create<InboxSignalsFilterStore>()(
  persist(
    (set) => ({
      sortField: "created_at",
      sortDirection: "desc",
      searchQuery: "",
      sourceProductFilter: [],
      priorityFilter: [],
      reportStateFilter: DEFAULT_INBOX_REPORT_STATE_FILTER,
      prFilter: "all",
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
      setSourceProductFilter: (sources) =>
        set({ sourceProductFilter: Array.from(new Set(sources)) }),
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
      toggleReportState: (reportState) =>
        set((state) => ({
          reportStateFilter: state.reportStateFilter.includes(reportState)
            ? state.reportStateFilter.filter((value) => value !== reportState)
            : [...state.reportStateFilter, reportState],
        })),
      setReportStateFilter: (states) =>
        set({ reportStateFilter: Array.from(new Set(states)) }),
      setPrFilter: (prFilter) => set({ prFilter }),
      clearSourceProductFilter: () => set({ sourceProductFilter: [] }),
      resetFilters: () =>
        set({
          searchQuery: "",
          sourceProductFilter: [],
          priorityFilter: [],
          reportStateFilter: DEFAULT_INBOX_REPORT_STATE_FILTER,
          prFilter: "all",
        }),
    }),
    {
      name: "inbox-signals-filter-storage",
      version: 3,
      migrate: (persisted, version) => {
        if (!persisted || typeof persisted !== "object") return persisted;
        const next = persisted as Record<string, unknown>;
        if (version >= 3) return next;
        const {
          statusFilter: _statusFilter,
          suggestedReviewerFilter: _suggestedReviewerFilter,
          hasInitializedSuggestedReviewerFilter:
            _hasInitializedSuggestedReviewerFilter,
          ...rest
        } = next;
        return {
          ...rest,
          reportStateFilter: DEFAULT_INBOX_REPORT_STATE_FILTER,
        };
      },
      partialize: (state) => ({
        sortField: state.sortField,
        sortDirection: state.sortDirection,
        sourceProductFilter: state.sourceProductFilter,
        priorityFilter: state.priorityFilter,
        reportStateFilter: state.reportStateFilter,
        prFilter: state.prFilter,
      }),
    },
  ),
);
