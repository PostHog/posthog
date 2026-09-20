import {
  type ChannelItemFilters,
  type ChannelItemGrouping,
  type ChannelItemSort,
  DEFAULT_CHANNEL_ITEM_FILTERS,
  DEFAULT_CHANNEL_ITEM_SORT,
} from "@posthog/core/canvas/channelItems";
import { create } from "zustand";
import { persist } from "zustand/middleware";

/** How the space's log draws a row: one line, or the card it has always been. */
export type SpaceActivityView = "list" | "cards";

/**
 * How a space's Activity tab is shown. Its own state rather than the Work
 * column's: the column is every space at once and the tab is one space, so a
 * repository filter that makes sense in one is noise in the other.
 *
 * Grouping here has no space option for the same reason — every row in a
 * space's log is in that space.
 */
interface SpaceActivityViewState {
  view: SpaceActivityView;
  filters: ChannelItemFilters;
  sort: ChannelItemSort;
  grouping: ChannelItemGrouping;
  setView: (view: SpaceActivityView) => void;
  setFilters: (filters: ChannelItemFilters) => void;
  setSort: (sort: ChannelItemSort) => void;
  setGrouping: (grouping: ChannelItemGrouping) => void;
}

export const useSpaceActivityViewStore = create<SpaceActivityViewState>()(
  persist(
    (set) => ({
      view: "list",
      filters: DEFAULT_CHANNEL_ITEM_FILTERS,
      sort: DEFAULT_CHANNEL_ITEM_SORT,
      grouping: "date",
      setView: (view) => set({ view }),
      setFilters: (filters) => set({ filters }),
      setSort: (sort) => set({ sort }),
      setGrouping: (grouping) => set({ grouping }),
    }),
    { name: "ph-space-activity-view" },
  ),
);
