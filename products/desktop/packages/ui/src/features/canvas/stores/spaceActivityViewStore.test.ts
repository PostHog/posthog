import {
  DEFAULT_CHANNEL_ITEM_FILTERS,
  FIRST_PARTY_CLIENT_SOURCES,
  WEB_SOURCE,
} from "@posthog/core/canvas/channelItems";
import { describe, expect, it } from "vitest";
import { useSpaceActivityViewStore } from "./spaceActivityViewStore";

describe("spaceActivityViewStore", () => {
  const { sources: _, ...filtersWithoutSources } = DEFAULT_CHANNEL_ITEM_FILTERS;

  it.each([
    {
      label: "saved sources",
      filters: {
        ...filtersWithoutSources,
        sources: ["user_created", "posthog_ai", "slack"],
      },
      expected: [...FIRST_PARTY_CLIENT_SOURCES, "slack"],
    },
    {
      label: "a legacy single source",
      filters: { ...filtersWithoutSources, source: "posthog_ai" },
      expected: [WEB_SOURCE],
    },
  ])(
    "rehydration maps old $label to client sources",
    async ({ filters, expected }) => {
      localStorage.setItem(
        "ph-space-activity-view",
        JSON.stringify({ state: { filters }, version: 0 }),
      );

      await useSpaceActivityViewStore.persist.rehydrate();

      const state = useSpaceActivityViewStore.getState();
      expect(state.filters.sources).toEqual(expected);
      expect(state.filters).not.toHaveProperty("source");
      localStorage.removeItem("ph-space-activity-view");
    },
  );
});
