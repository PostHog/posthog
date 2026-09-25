import {
  type ChannelItemFilters,
  type ChannelItemGrouping,
  type ChannelItemSort,
  DEFAULT_CHANNEL_ITEM_FILTERS,
  DEFAULT_CHANNEL_ITEM_SORT,
  migrateSourceFilter,
} from "@posthog/core/canvas/channelItems";
import type { SpaceActivityType } from "@posthog/ui/features/canvas/components/channelFeedDisplay";
import { ALL_SPACE_ACTIVITY_TYPES } from "@posthog/ui/features/canvas/components/channelFeedDisplay";
import { create } from "zustand";
import { persist } from "zustand/middleware";

export type SpaceActivityView = "list" | "cards";

interface SpaceActivityViewState {
  view: SpaceActivityView;
  types: SpaceActivityType[];
  filters: ChannelItemFilters;
  sort: ChannelItemSort;
  grouping: ChannelItemGrouping;
  setView: (view: SpaceActivityView) => void;
  setTypes: (types: SpaceActivityType[]) => void;
  setFilters: (filters: ChannelItemFilters) => void;
  setSort: (sort: ChannelItemSort) => void;
  setGrouping: (grouping: ChannelItemGrouping) => void;
}

export const useSpaceActivityViewStore = create<SpaceActivityViewState>()(
  persist(
    (set) => ({
      view: "list",
      types: [...ALL_SPACE_ACTIVITY_TYPES],
      filters: DEFAULT_CHANNEL_ITEM_FILTERS,
      sort: DEFAULT_CHANNEL_ITEM_SORT,
      grouping: "date",
      setView: (view) => set({ view }),
      setTypes: (types) => set(types.length > 0 ? { types } : {}),
      setFilters: (filters) => set({ filters }),
      setSort: (sort) => set({ sort }),
      setGrouping: (grouping) => set({ grouping }),
    }),
    {
      name: "ph-space-activity-view",
      merge: (persisted, current) => {
        const saved = persisted as Partial<SpaceActivityViewState> | undefined;
        const savedTypes = saved?.types?.filter((type) =>
          ALL_SPACE_ACTIVITY_TYPES.includes(type),
        );
        return {
          ...current,
          ...saved,
          types:
            savedTypes && savedTypes.length > 0 ? savedTypes : current.types,
          filters: {
            ...current.filters,
            ...(saved?.filters ? migrateSourceFilter(saved.filters) : {}),
            kind: "any",
          },
        };
      },
    },
  ),
);
