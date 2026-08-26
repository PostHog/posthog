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
});
