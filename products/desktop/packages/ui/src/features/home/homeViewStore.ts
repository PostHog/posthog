import type {
  HomeFilters,
  HomeGroupBy,
  HomeSort,
} from "@posthog/core/home/homeFilters";
import {
  NO_HOME_FILTERS,
  toggleHomeFilter,
} from "@posthog/core/home/homeFilters";
import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * How the home table is arranged right now. View state, so it lives here rather
 * than beside the projects: it says nothing about the work, only about how this
 * reader is looking at it.
 *
 * The search query is deliberately not persisted. A filter left on is state the
 * table explains with a badge; a query restored from last week is a table that
 * looks empty for no visible reason.
 */
interface HomeViewState {
  query: string;
  filters: HomeFilters;
  groupBy: HomeGroupBy;
  sort: HomeSort;
  collapsedGroups: Record<string, boolean>;

  setQuery: (query: string) => void;
  toggleFilter: <K extends keyof HomeFilters>(
    facet: K,
    value: HomeFilters[K][number],
  ) => void;
  clearFilters: () => void;
  setGroupBy: (groupBy: HomeGroupBy) => void;
  setSort: (sort: HomeSort) => void;
  toggleGroup: (key: string) => void;
}

export const useHomeViewStore = create<HomeViewState>()(
  persist(
    (set) => ({
      query: "",
      filters: NO_HOME_FILTERS,
      groupBy: "status",
      sort: "recent",
      collapsedGroups: {},

      setQuery: (query) => set({ query }),
      toggleFilter: (facet, value) =>
        set((state) => ({
          filters: toggleHomeFilter(state.filters, facet, value),
        })),
      clearFilters: () => set({ filters: NO_HOME_FILTERS }),
      setGroupBy: (groupBy) => set({ groupBy }),
      setSort: (sort) => set({ sort }),
      toggleGroup: (key) =>
        set((state) => ({
          collapsedGroups: {
            ...state.collapsedGroups,
            [key]: !state.collapsedGroups[key],
          },
        })),
    }),
    {
      name: "home-view",
      storage: electronStorage,
      partialize: ({ filters, groupBy, sort, collapsedGroups }) => ({
        filters,
        groupBy,
        sort,
        collapsedGroups,
      }),
    },
  ),
);
