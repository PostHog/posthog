import { describe, expect, it } from "vitest";
import { shapeFlagAudience } from "./flag-audience";
import type { Schemas } from "./generated";

// The shaper only reads the fields it shows; build minimal inputs and cast.
function flagWith(filters: unknown): Schemas.FeatureFlag {
  return { id: 1, key: "test-flag", active: true, filters } as unknown as Schemas.FeatureFlag;
}

describe("flag audience shaping", () => {
  it("treats an explicit null aggregation as person targeting", () => {
    const audience = shapeFlagAudience(
      flagWith({
        aggregation_group_type_index: 0,
        groups: [
          {
            properties: [
              { type: "cohort", key: "id", value: 7, cohort_name: "Power users" },
            ],
            rollout_percentage: 25,
            aggregation_group_type_index: null,
          },
        ],
      }),
    );

    expect(audience.headline).toBe("On for 25% of Power users.");
    expect(audience.rules[0].conditions[0].subject).toBe("Person");
  });

  it("reports nobody for a flag with no release conditions", () => {
    const audience = shapeFlagAudience(flagWith({ groups: [] }));

    expect(audience.rules).toEqual([]);
    expect(audience.headline).toBe("On for nobody.");
    expect(audience.summary).toBe(
      "The flag has no release conditions, so every check returns false.",
    );
  });

  it("marks rules after a 100% catch-all as unreachable", () => {
    const audience = shapeFlagAudience(
      flagWith({
        multivariate: { variants: [{ key: "a" }, { key: "b" }] },
        groups: [
          { rollout_percentage: 100 },
          {
            properties: [{ key: "plan", operator: "exact", value: "pro" }],
            rollout_percentage: 50,
            variant: "b",
          },
        ],
      }),
    );

    expect(audience.rules.map((rule) => rule.reachable)).toEqual([
      true,
      false,
    ]);
    // The shadowed rule must not promise its variant in the summary.
    expect(audience.summary).not.toContain("b");
  });

  it("keeps the summary consistent with the hidden fallback row on a catch-all", () => {
    const audience = shapeFlagAudience(
      flagWith({ groups: [{ rollout_percentage: 100 }] }),
    );

    expect(audience.fallbackReachable).toBe(false);
    expect(audience.summary).not.toContain("Everyone else gets false.");
  });

  it("renders a readable label for operators that only reach flags through the API", () => {
    const audience = shapeFlagAudience(
      flagWith({
        groups: [
          {
            properties: [
              { key: "app_version", operator: "semver_caret", value: "2.1.0" },
            ],
            rollout_percentage: 100,
          },
        ],
      }),
    );

    expect(audience.rules[0].conditions[0].operator).toBe(
      "is version in caret range",
    );
  });
});
