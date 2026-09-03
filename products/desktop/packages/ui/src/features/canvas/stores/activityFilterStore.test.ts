import { beforeEach, describe, expect, it, vi } from "vitest";

describe("activityFilterStore", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  it("starts with mentions included and Self-driving excluded", async () => {
    const { useActivityFilterStore } = await import("./activityFilterStore");

    expect(useActivityFilterStore.getState()).toMatchObject({
      mentionsEnabled: true,
      inboxEnabledByAuthIdentity: {},
      inboxScope: "for-you",
      inboxSourceProductFilter: [],
      inboxPrFilter: "all",
      inboxSortField: "priority",
      inboxSortDirection: "asc",
      inboxPriorityFilter: ["P1"],
    });
  });

  it("keeps the Self-driving opt-in separate for each project", async () => {
    const { useActivityFilterStore } = await import("./activityFilterStore");

    useActivityFilterStore.getState().setInboxEnabled("us:1", true);

    expect(
      useActivityFilterStore.getState().inboxEnabledByAuthIdentity,
    ).toEqual({ "us:1": true });
    expect(
      useActivityFilterStore.getState().inboxEnabledByAuthIdentity["eu:1"] ??
        false,
    ).toBe(false);
  });

  it("resets the menu filters without changing unread mode or other projects", async () => {
    const { hasActiveActivityMenuFilters, useActivityFilterStore } =
      await import("./activityFilterStore");
    const state = useActivityFilterStore.getState();

    state.setUnreadsOnly(true);
    state.setMentionsEnabled(false);
    state.setInboxEnabled("us:1", true);
    state.setInboxEnabled("eu:1", true);
    state.setInboxScope("entire-project");
    state.toggleInboxSourceProduct("error_tracking");
    state.setInboxPrFilter("with_pr");
    state.setInboxSort("created_at", "desc");
    state.toggleInboxPriority("P2");
    expect(
      hasActiveActivityMenuFilters(useActivityFilterStore.getState(), "us:1"),
    ).toBe(true);
    useActivityFilterStore.getState().resetMenuFilters("us:1");

    expect(useActivityFilterStore.getState()).toMatchObject({
      unreadsOnly: true,
      mentionsEnabled: true,
      inboxEnabledByAuthIdentity: { "us:1": false, "eu:1": true },
      inboxScope: "for-you",
      inboxSourceProductFilter: [],
      inboxPrFilter: "all",
      inboxSortField: "priority",
      inboxSortDirection: "asc",
      inboxPriorityFilter: ["P1"],
    });
    expect(
      hasActiveActivityMenuFilters(useActivityFilterStore.getState(), "us:1"),
    ).toBe(false);
  });
});
