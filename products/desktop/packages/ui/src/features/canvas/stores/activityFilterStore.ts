import type {
  SignalReportPriority,
  SourceProduct,
} from "@posthog/shared/types";
import type { InboxSortField } from "@posthog/ui/features/inbox/filterOptions";
import type { InboxPrFilter } from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";
import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ActivityInboxScope = "for-you" | "entire-project";

const DEFAULT_ACTIVITY_MENU_FILTERS = {
  mentionsEnabled: true,
  inboxScope: "for-you" as const,
  inboxSourceProductFilter: [] as SourceProduct[],
  inboxPrFilter: "all" as InboxPrFilter,
  inboxSortField: "priority" as InboxSortField,
  inboxSortDirection: "asc" as const,
  inboxPriorityFilter: ["P1"] as SignalReportPriority[],
};

interface ActivityFilterStore {
  /** Show only activity that hasn't been read yet. */
  unreadsOnly: boolean;
  mentionsEnabled: boolean;
  inboxEnabledByAuthIdentity: Record<string, boolean>;
  inboxScope: ActivityInboxScope;
  inboxSourceProductFilter: SourceProduct[];
  inboxPrFilter: InboxPrFilter;
  inboxSortField: InboxSortField;
  inboxSortDirection: "asc" | "desc";
  inboxPriorityFilter: SignalReportPriority[];
  setUnreadsOnly: (unreadsOnly: boolean) => void;
  setMentionsEnabled: (mentionsEnabled: boolean) => void;
  setInboxEnabled: (authIdentity: string, inboxEnabled: boolean) => void;
  setInboxScope: (inboxScope: ActivityInboxScope) => void;
  toggleInboxSourceProduct: (source: SourceProduct) => void;
  clearInboxSourceProductFilter: () => void;
  setInboxPrFilter: (inboxPrFilter: InboxPrFilter) => void;
  setInboxSort: (
    inboxSortField: InboxSortField,
    inboxSortDirection: "asc" | "desc",
  ) => void;
  toggleInboxPriority: (priority: SignalReportPriority) => void;
  clearInboxPriorityFilter: () => void;
  resetMenuFilters: (authIdentity: string | null) => void;
}

export function hasActiveActivityMenuFilters(
  state: ActivityFilterStore,
  authIdentity: string | null,
): boolean {
  return (
    state.mentionsEnabled !== DEFAULT_ACTIVITY_MENU_FILTERS.mentionsEnabled ||
    (authIdentity
      ? (state.inboxEnabledByAuthIdentity[authIdentity] ?? false)
      : false) ||
    state.inboxScope !== DEFAULT_ACTIVITY_MENU_FILTERS.inboxScope ||
    state.inboxSourceProductFilter.length > 0 ||
    state.inboxPrFilter !== DEFAULT_ACTIVITY_MENU_FILTERS.inboxPrFilter ||
    state.inboxSortField !== DEFAULT_ACTIVITY_MENU_FILTERS.inboxSortField ||
    state.inboxSortDirection !==
      DEFAULT_ACTIVITY_MENU_FILTERS.inboxSortDirection ||
    state.inboxPriorityFilter.length !== 1 ||
    state.inboxPriorityFilter[0] !==
      DEFAULT_ACTIVITY_MENU_FILTERS.inboxPriorityFilter[0]
  );
}

// Per-device preference shared by the Activity popover and the Activity page, so
// the filter you set on one is the filter you find on the other.
export const useActivityFilterStore = create<ActivityFilterStore>()(
  persist(
    (set) => ({
      unreadsOnly: false,
      inboxEnabledByAuthIdentity: {},
      ...DEFAULT_ACTIVITY_MENU_FILTERS,
      setUnreadsOnly: (unreadsOnly) => set({ unreadsOnly }),
      setMentionsEnabled: (mentionsEnabled) => set({ mentionsEnabled }),
      setInboxEnabled: (authIdentity, inboxEnabled) =>
        set((state) => ({
          inboxEnabledByAuthIdentity: {
            ...state.inboxEnabledByAuthIdentity,
            [authIdentity]: inboxEnabled,
          },
        })),
      setInboxScope: (inboxScope) => set({ inboxScope }),
      toggleInboxSourceProduct: (source) =>
        set((state) => ({
          inboxSourceProductFilter: state.inboxSourceProductFilter.includes(
            source,
          )
            ? state.inboxSourceProductFilter.filter((item) => item !== source)
            : [...state.inboxSourceProductFilter, source],
        })),
      clearInboxSourceProductFilter: () =>
        set({ inboxSourceProductFilter: [] }),
      setInboxPrFilter: (inboxPrFilter) => set({ inboxPrFilter }),
      setInboxSort: (inboxSortField, inboxSortDirection) =>
        set({ inboxSortField, inboxSortDirection }),
      toggleInboxPriority: (priority) =>
        set((state) => ({
          inboxPriorityFilter: state.inboxPriorityFilter.includes(priority)
            ? state.inboxPriorityFilter.filter((item) => item !== priority)
            : [...state.inboxPriorityFilter, priority],
        })),
      clearInboxPriorityFilter: () => set({ inboxPriorityFilter: [] }),
      resetMenuFilters: (authIdentity) =>
        set((state) => ({
          ...DEFAULT_ACTIVITY_MENU_FILTERS,
          inboxEnabledByAuthIdentity: authIdentity
            ? {
                ...state.inboxEnabledByAuthIdentity,
                [authIdentity]: false,
              }
            : state.inboxEnabledByAuthIdentity,
        })),
    }),
    {
      name: "activity-filter-storage",
      version: 1,
      migrate: (persisted, version) => {
        if (version >= 1 || !persisted || typeof persisted !== "object") {
          return persisted;
        }
        const { inboxEnabled: _inboxEnabled, ...rest } = persisted as Record<
          string,
          unknown
        >;
        return { ...rest, inboxEnabledByAuthIdentity: {} };
      },
      partialize: (state) => ({
        unreadsOnly: state.unreadsOnly,
        mentionsEnabled: state.mentionsEnabled,
        inboxEnabledByAuthIdentity: state.inboxEnabledByAuthIdentity,
        inboxScope: state.inboxScope,
        inboxSourceProductFilter: state.inboxSourceProductFilter,
        inboxPrFilter: state.inboxPrFilter,
        inboxSortField: state.inboxSortField,
        inboxSortDirection: state.inboxSortDirection,
        inboxPriorityFilter: state.inboxPriorityFilter,
      }),
    },
  ),
);
