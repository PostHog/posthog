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
});
