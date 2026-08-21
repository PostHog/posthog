import { beforeEach, describe, expect, it } from "vitest";
import { useInboxSignalsFilterStore } from "./inboxSignalsFilterStore";

describe("inboxSignalsFilterStore", () => {
  beforeEach(() => {
    localStorage.clear();
    useInboxSignalsFilterStore.setState({
      sortField: "total_weight",
      sortDirection: "desc",
      searchQuery: "",
      sourceProductFilter: [],
      priorityFilter: [],
    });
  });

  it("has correct defaults", () => {
    const state = useInboxSignalsFilterStore.getState();
    expect(state.sortField).toBe("total_weight");
    expect(state.sortDirection).toBe("desc");
    expect(state.searchQuery).toBe("");
    expect(state.sourceProductFilter).toEqual([]);
    expect(state.priorityFilter).toEqual([]);
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

  it("resetFilters restores defaults across surviving filter fields", () => {
    const store = useInboxSignalsFilterStore.getState();
    store.setSearchQuery("hello");
    store.toggleSourceProduct("github");
    store.setPriorityFilter(["P0", "P1"]);

    useInboxSignalsFilterStore.getState().resetFilters();

    const state = useInboxSignalsFilterStore.getState();
    expect(state.searchQuery).toBe("");
    expect(state.sourceProductFilter).toEqual([]);
    expect(state.priorityFilter).toEqual([]);
  });

  it("resetFilters preserves sort preferences", () => {
    useInboxSignalsFilterStore.getState().setSort("created_at", "asc");

    useInboxSignalsFilterStore.getState().resetFilters();

    const state = useInboxSignalsFilterStore.getState();
    expect(state.sortField).toBe("created_at");
    expect(state.sortDirection).toBe("asc");
  });

  it("migrates pre-v2 localStorage by dropping the dead filter slots", () => {
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
    expect(
      (state as unknown as Record<string, unknown>).statusFilter,
    ).toBeUndefined();
    expect(
      (state as unknown as Record<string, unknown>).suggestedReviewerFilter,
    ).toBeUndefined();
  });
});
