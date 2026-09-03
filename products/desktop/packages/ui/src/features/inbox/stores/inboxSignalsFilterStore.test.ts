import { beforeEach, describe, expect, it } from "vitest";
import {
  hasActiveInboxFilters,
  useInboxSignalsFilterStore,
} from "./inboxSignalsFilterStore";

describe("inboxSignalsFilterStore", () => {
  beforeEach(() => {
    localStorage.clear();
    useInboxSignalsFilterStore.setState({
      sortField: "total_weight",
      sortDirection: "desc",
      searchQuery: "",
      sourceProductFilter: [],
      priorityFilter: [],
      reportStateFilter: ["review_and_merge", "needs_decision"],
      prFilter: "all",
    });
  });

  it("has correct defaults", () => {
    const state = useInboxSignalsFilterStore.getState();
    expect(state.sortField).toBe("total_weight");
    expect(state.sortDirection).toBe("desc");
    expect(state.searchQuery).toBe("");
    expect(state.sourceProductFilter).toEqual([]);
    expect(state.priorityFilter).toEqual([]);
    expect(state.reportStateFilter).toEqual([
      "review_and_merge",
      "needs_decision",
    ]);
  });

  it("setSort updates field and direction", () => {
    useInboxSignalsFilterStore.getState().setSort("created_at", "asc");
    const state = useInboxSignalsFilterStore.getState();
    expect(state.sortField).toBe("created_at");
    expect(state.sortDirection).toBe("asc");
  });

  it("setSearchQuery updates query", () => {
    useInboxSignalsFilterStore.getState().setSearchQuery("login error");
    expect(useInboxSignalsFilterStore.getState().searchQuery).toBe(
      "login error",
    );
  });

  it("persists sortField and sortDirection", () => {
    useInboxSignalsFilterStore.getState().setSort("created_at", "desc");
    const raw = localStorage.getItem("inbox-signals-filter-storage");
    expect(raw).toBeTruthy();
    const persisted = JSON.parse(raw as string);
    expect(persisted.state.sortField).toBe("created_at");
    expect(persisted.state.sortDirection).toBe("desc");
  });

  it("does not persist searchQuery", () => {
    useInboxSignalsFilterStore.getState().setSearchQuery("test");
    const raw = localStorage.getItem("inbox-signals-filter-storage");
    expect(raw).toBeTruthy();
    const persisted = JSON.parse(raw as string);
    expect(persisted.state.searchQuery).toBeUndefined();
  });

  it("togglePriority adds and removes priorities", () => {
    useInboxSignalsFilterStore.getState().togglePriority("P0");
    expect(useInboxSignalsFilterStore.getState().priorityFilter).toEqual([
      "P0",
    ]);

    useInboxSignalsFilterStore.getState().togglePriority("P1");
    expect(useInboxSignalsFilterStore.getState().priorityFilter).toEqual([
      "P0",
      "P1",
    ]);

    useInboxSignalsFilterStore.getState().togglePriority("P0");
    expect(useInboxSignalsFilterStore.getState().priorityFilter).toEqual([
      "P1",
    ]);
  });

  it("setPriorityFilter resets priorities back to Any (empty)", () => {
    useInboxSignalsFilterStore.getState().setPriorityFilter(["P0", "P1"]);

    useInboxSignalsFilterStore.getState().setPriorityFilter([]);

    expect(useInboxSignalsFilterStore.getState().priorityFilter).toEqual([]);
  });

  it("clearSourceProductFilter resets sources back to Any (empty)", () => {
    useInboxSignalsFilterStore.getState().toggleSourceProduct("github");
    useInboxSignalsFilterStore.getState().toggleSourceProduct("linear");

    useInboxSignalsFilterStore.getState().clearSourceProductFilter();

    expect(useInboxSignalsFilterStore.getState().sourceProductFilter).toEqual(
      [],
    );
  });

  it("toggling off the last source is equivalent to Any (empty)", () => {
    useInboxSignalsFilterStore.getState().toggleSourceProduct("github");
    useInboxSignalsFilterStore.getState().toggleSourceProduct("github");

    expect(useInboxSignalsFilterStore.getState().sourceProductFilter).toEqual(
      [],
    );
  });

  it("setPriorityFilter de-duplicates priorities", () => {
    useInboxSignalsFilterStore.getState().setPriorityFilter(["P0", "P1", "P0"]);

    expect(useInboxSignalsFilterStore.getState().priorityFilter).toEqual([
      "P0",
      "P1",
    ]);
  });

  it("persists priorityFilter", () => {
    useInboxSignalsFilterStore.getState().setPriorityFilter(["P0", "P1"]);

    const raw = localStorage.getItem("inbox-signals-filter-storage");
    expect(raw).toBeTruthy();
    const persisted = JSON.parse(raw as string);

    expect(persisted.state.priorityFilter).toEqual(["P0", "P1"]);
  });

  it("restores filter and sort preferences after a restart", async () => {
    const store = useInboxSignalsFilterStore.getState();
    store.setSort("created_at", "asc");
    store.setPriorityFilter(["P0", "P1"]);
    store.setReportStateFilter(["dismissed"]);
    const persisted = localStorage.getItem("inbox-signals-filter-storage");

    useInboxSignalsFilterStore.setState({
      sortField: "total_weight",
      sortDirection: "desc",
      priorityFilter: [],
      reportStateFilter: ["review_and_merge", "needs_decision"],
    });
    localStorage.setItem("inbox-signals-filter-storage", persisted as string);
    await useInboxSignalsFilterStore.persist.rehydrate();

    const restored = useInboxSignalsFilterStore.getState();
    expect(restored.sortField).toBe("created_at");
    expect(restored.sortDirection).toBe("asc");
    expect(restored.priorityFilter).toEqual(["P0", "P1"]);
    expect(restored.reportStateFilter).toEqual(["dismissed"]);
  });

  it("resetFilters restores defaults across surviving filter fields", () => {
    const store = useInboxSignalsFilterStore.getState();
    store.setSearchQuery("hello");
    store.toggleSourceProduct("github");
    store.setPriorityFilter(["P0", "P1"]);
    store.toggleReportState("resolved");

    useInboxSignalsFilterStore.getState().resetFilters();

    const state = useInboxSignalsFilterStore.getState();
    expect(state.searchQuery).toBe("");
    expect(state.sourceProductFilter).toEqual([]);
    expect(state.priorityFilter).toEqual([]);
    expect(state.reportStateFilter).toEqual([
      "review_and_merge",
      "needs_decision",
    ]);
  });

  it("resetFilters preserves sort preferences", () => {
    useInboxSignalsFilterStore.getState().setSort("created_at", "asc");

    useInboxSignalsFilterStore.getState().resetFilters();

    const state = useInboxSignalsFilterStore.getState();
    expect(state.sortField).toBe("created_at");
    expect(state.sortDirection).toBe("asc");
  });

  it.each([
    ["no filters", () => {}, false],
    [
      "a search query",
      (s: ReturnType<typeof useInboxSignalsFilterStore.getState>) =>
        s.setSearchQuery("login"),
      true,
    ],
    [
      "a whitespace-only search query",
      (s: ReturnType<typeof useInboxSignalsFilterStore.getState>) =>
        s.setSearchQuery("   "),
      false,
    ],
    [
      "a source filter",
      (s: ReturnType<typeof useInboxSignalsFilterStore.getState>) =>
        s.toggleSourceProduct("github"),
      true,
    ],
    [
      "a priority filter",
      (s: ReturnType<typeof useInboxSignalsFilterStore.getState>) =>
        s.setPriorityFilter(["P0"]),
      true,
    ],
    [
      "a PR filter",
      (s: ReturnType<typeof useInboxSignalsFilterStore.getState>) =>
        s.setPrFilter("with_pr"),
      true,
    ],
    // Sort only reorders the list, so it must not read as an active filter.
    [
      "only a non-default sort",
      (s: ReturnType<typeof useInboxSignalsFilterStore.getState>) =>
        s.setSort("created_at", "asc"),
      false,
    ],
  ] as const)(
    "hasActiveInboxFilters is %s -> %s",
    (_label, apply, expected) => {
      apply(useInboxSignalsFilterStore.getState());
      expect(hasActiveInboxFilters(useInboxSignalsFilterStore.getState())).toBe(
        expected,
      );
    },
  );

  it("treats a changed report state selection as an active report filter", () => {
    useInboxSignalsFilterStore.getState().toggleReportState("resolved");

    expect(
      hasActiveInboxFilters(useInboxSignalsFilterStore.getState(), {
        includeReportStateFilter: true,
      }),
    ).toBe(true);
  });

  it("ignores a saved source filter when the surface hides that control", () => {
    useInboxSignalsFilterStore.getState().toggleSourceProduct("github");

    expect(
      hasActiveInboxFilters(useInboxSignalsFilterStore.getState(), {
        includeSourceFilter: false,
      }),
    ).toBe(false);
  });

  it("migrates old localStorage by dropping dead slots and adding report states", () => {
    localStorage.setItem(
      "inbox-signals-filter-storage",
      JSON.stringify({
        version: 1,
        state: {
          sortField: "created_at",
          sortDirection: "asc",
          sourceProductFilter: ["github"],
          priorityFilter: ["P1"],
          statusFilter: ["ready"],
          suggestedReviewerFilter: ["uuid-1"],
          hasInitializedSuggestedReviewerFilter: true,
        },
      }),
    );

    // Force a rehydrate so the migration runs.
    useInboxSignalsFilterStore.persist.rehydrate();
    const state = useInboxSignalsFilterStore.getState();
    expect(state.sortField).toBe("created_at");
    expect(state.priorityFilter).toEqual(["P1"]);
    expect(state.sourceProductFilter).toEqual(["github"]);
    expect(state.reportStateFilter).toEqual([
      "review_and_merge",
      "needs_decision",
    ]);
    expect(
      (state as unknown as Record<string, unknown>).statusFilter,
    ).toBeUndefined();
    expect(
      (state as unknown as Record<string, unknown>).suggestedReviewerFilter,
    ).toBeUndefined();
  });
});
