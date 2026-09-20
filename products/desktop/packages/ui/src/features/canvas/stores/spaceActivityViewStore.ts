import {
  type ChannelItemFilters,
  type ChannelItemGrouping,
  type ChannelItemSort,
  DEFAULT_CHANNEL_ITEM_FILTERS,
  DEFAULT_CHANNEL_ITEM_SORT,
} from "@posthog/core/canvas/channelItems";
import { create } from "zustand";
import { persist } from "zustand/middleware";

export type SpaceActivityView = "list" | "cards";

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
