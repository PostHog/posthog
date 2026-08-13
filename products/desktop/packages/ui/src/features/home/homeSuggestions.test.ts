import type { HomeFeatureFlag } from "@posthog/core/home/homeSchemas";
import { describe, expect, it } from "vitest";
import { homeFlagSuggestions, spaceNameForFlag } from "./homeSuggestions";

function flag(overrides: Partial<HomeFeatureFlag> = {}): HomeFeatureFlag {
  return {
    id: 1,
    key: "new-checkout",
    name: "The rebuilt checkout",
    active: true,
    rolloutPercentage: 25,
    hasExperiment: false,
    createdAt: 0,
    yours: true,
    createdBy: "Ada",
    ...overrides,
  };
}

describe("homeFlagSuggestions", () => {
  it("names the space a flag would start, without doubling the prefix", () => {
    expect(spaceNameForFlag("new_checkout")).toBe("feature-new-checkout");
    expect(spaceNameForFlag("feature-billing")).toBe("feature-billing");
  });

  it("leaves out flags that already drive an experiment", () => {
    const suggestions = homeFlagSuggestions({
      flags: [flag({ id: 1 }), flag({ id: 2, key: "ab", hasExperiment: true })],
      channels: [],
    });

    expect(suggestions.map((s) => s.flag.id)).toEqual([1]);
  });

  it.each([
    ["the name Home proposes", "feature-new-checkout"],
    ["the flag key on its own", "new-checkout"],
  ])("finds an existing space under %s", (_case, channelName) => {
    const suggestions = homeFlagSuggestions({
      flags: [flag()],
      channels: [{ id: "chan-1", name: channelName }],
    });

    expect(suggestions[0].existingSpace).toEqual({
      id: "chan-1",
      name: channelName,
    });
  });

  it("offers a flag whose space does not exist yet", () => {
    const suggestions = homeFlagSuggestions({
      flags: [flag()],
      channels: [{ id: "chan-1", name: "billing" }],
    });

    expect(suggestions[0].existingSpace).toBeNull();
    expect(suggestions[0].spaceName).toBe("feature-new-checkout");
  });

  it("keeps the service's order and caps the list", () => {
    const suggestions = homeFlagSuggestions({
      flags: [
        flag({ id: 1, key: "a" }),
        flag({ id: 2, key: "b" }),
        flag({ id: 3, key: "c" }),
      ],
      channels: [],
      limit: 2,
    });

    expect(suggestions.map((s) => s.flag.key)).toEqual(["a", "b"]);
  });
});
