import type {
  SignalReportPriority,
  SourceProduct,
} from "@posthog/shared/types";
import type { InboxSortField } from "@posthog/ui/features/inbox/filterOptions";
import type { InboxPrFilter } from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";
import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ActivityInboxScope = "for-you" | "entire-project";

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
}

// Per-device preference shared by the Activity popover and the Activity page, so
// the filter you set on one is the filter you find on the other.
export const useActivityFilterStore = create<ActivityFilterStore>()(
  persist(
    (set) => ({
      unreadsOnly: false,
      mentionsEnabled: true,
      inboxEnabledByAuthIdentity: {},
      inboxScope: "for-you",
      inboxSourceProductFilter: [],
      inboxPrFilter: "all",
      inboxSortField: "priority",
      inboxSortDirection: "asc",
      inboxPriorityFilter: ["P1"],
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
