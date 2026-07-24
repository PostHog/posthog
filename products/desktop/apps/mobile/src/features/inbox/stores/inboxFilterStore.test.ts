import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@react-native-async-storage/async-storage", () => ({
  default: {
    getItem: vi.fn(),
    setItem: vi.fn(),
    removeItem: vi.fn(),
  },
}));

import { type SourceProduct, useInboxFilterStore } from "./inboxFilterStore";

describe("inboxFilterStore", () => {
  beforeEach(() => {
    useInboxFilterStore.getState().resetFilters();
  });

  it.each<SourceProduct>(["signals_scout", "error_tracking", "sentry"])(
    "toggles %s in and out of the source filter",
    (source) => {
      const { toggleSourceProduct } = useInboxFilterStore.getState();

      toggleSourceProduct(source);
      expect(useInboxFilterStore.getState().sourceProductFilter).toEqual([
        source,
      ]);

      toggleSourceProduct(source);
      expect(useInboxFilterStore.getState().sourceProductFilter).toEqual([]);
    },
  );

  it("clears the source filter", () => {
    const { toggleSourceProduct, clearSourceProductFilter } =
      useInboxFilterStore.getState();

    toggleSourceProduct("github");
    toggleSourceProduct("linear");
    expect(useInboxFilterStore.getState().sourceProductFilter).toEqual([
      "github",
      "linear",
    ]);

    clearSourceProductFilter();
    expect(useInboxFilterStore.getState().sourceProductFilter).toEqual([]);
  });
});

const INITIAL_STATE = useInboxFilterStore.getState();

describe("inboxFilterStore priority filter", () => {
  beforeEach(() => {
    useInboxFilterStore.setState(INITIAL_STATE, true);
  });

  it("starts empty (no priority filter)", () => {
    expect(useInboxFilterStore.getState().priorityFilter).toEqual([]);
  });

  it("toggles a priority on and off", () => {
    const { togglePriority } = useInboxFilterStore.getState();

    togglePriority("P0");
    expect(useInboxFilterStore.getState().priorityFilter).toEqual(["P0"]);

    togglePriority("P0");
    expect(useInboxFilterStore.getState().priorityFilter).toEqual([]);
  });

  it("accumulates multiple priorities", () => {
    const { togglePriority } = useInboxFilterStore.getState();

    togglePriority("P0");
    togglePriority("P2");
    expect(useInboxFilterStore.getState().priorityFilter).toEqual(["P0", "P2"]);
  });

  it("dedupes when set directly", () => {
    useInboxFilterStore.getState().setPriorityFilter(["P1", "P1", "P3"]);
    expect(useInboxFilterStore.getState().priorityFilter).toEqual(["P1", "P3"]);
  });

  it("clears the priority filter on reset", () => {
    useInboxFilterStore.getState().setPriorityFilter(["P0", "P1"]);
    useInboxFilterStore.getState().resetFilters();
    expect(useInboxFilterStore.getState().priorityFilter).toEqual([]);
  });
});
