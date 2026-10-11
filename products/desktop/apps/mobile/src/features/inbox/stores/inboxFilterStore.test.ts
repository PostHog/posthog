import type { SourceProduct } from "@posthog/shared";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@react-native-async-storage/async-storage", () => ({
  default: {
    getItem: vi.fn(),
    setItem: vi.fn(),
    removeItem: vi.fn(),
  },
}));

import {
  migrateInboxFilterState,
  resolveSuggestedReviewerFilter,
  useInboxFilterStore,
} from "./inboxFilterStore";

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

describe("inboxFilterStore suggested reviewer scope", () => {
  const ME = "00000000-0000-0000-0000-000000000001";
  const TEAMMATE = "00000000-0000-0000-0000-000000000002";

  beforeEach(() => {
    useInboxFilterStore.setState(INITIAL_STATE, true);
  });

  it.each<[string, string[] | null, string | undefined, string[] | null]>([
    ["defaults to the current user", null, ME, [ME]],
    ["waits while the current user loads", null, undefined, null],
    ["keeps a cleared filter as the whole project", [], ME, []],
    ["keeps an explicit selection", [TEAMMATE], ME, [TEAMMATE]],
  ])("%s", (_name, stored, currentUserUuid, expected) => {
    expect(resolveSuggestedReviewerFilter(stored, currentUserUuid)).toEqual(
      expected,
    );
  });

  it.each<[string, number, string[], string[] | null]>([
    ["moves an untouched v0 filter to the default", 0, [], null],
    ["keeps an explicit v0 selection", 0, [TEAMMATE], [TEAMMATE]],
    ["leaves a v1 cleared filter alone", 1, [], []],
  ])("%s", (_name, version, stored, expected) => {
    const migrated = migrateInboxFilterState(
      { ...INITIAL_STATE, suggestedReviewerFilter: stored },
      version,
    );
    expect(migrated.suggestedReviewerFilter).toEqual(expected);
  });

  it.each<[string, string, string[]]>([
    ["deselecting yourself shows the whole project", ME, []],
    ["adding a teammate keeps yourself selected", TEAMMATE, [ME, TEAMMATE]],
  ])("from the default scope, %s", (_name, toggled, expected) => {
    useInboxFilterStore.getState().toggleSuggestedReviewer(toggled, ME);
    expect(useInboxFilterStore.getState().suggestedReviewerFilter).toEqual(
      expected,
    );
  });
});
