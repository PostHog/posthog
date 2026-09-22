import { describe, expect, it } from "vitest";
import { shapeFlagAudience, targetedDistinctIds } from "./flag-audience";
import type { Schemas } from "./generated";

// The shaper only reads the fields it shows; build minimal inputs and cast.
function flagWith(filters: unknown): Schemas.FeatureFlag {
  return {
    id: 1,
    key: "test-flag",
    active: true,
    filters,
  } as unknown as Schemas.FeatureFlag;
}

describe("flag audience shaping", () => {
  it("treats an explicit null aggregation as person targeting", () => {
    const audience = shapeFlagAudience(
      flagWith({
        aggregation_group_type_index: 0,
        groups: [
          {
            properties: [
              {
                type: "cohort",
                key: "id",
                value: 7,
                cohort_name: "Power users",
              },
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

    expect(audience.rules.map((rule) => rule.reachable)).toEqual([true, false]);
    expect(audience.fallbackReachable).toBe(false);
    // The shadowed rule must not appear in the headline.
    expect(audience.headline).toBe("Split into 2 variants for everyone.");
  });

  it("keeps group-scope rules out of the guaranteed catch-all", () => {
    const audience = shapeFlagAudience(
      flagWith({
        aggregation_group_type_index: 0,
        groups: [{ rollout_percentage: 100 }],
      }),
    );

    expect(audience.rules[0].isGroup).toBe(true);
    expect(audience.fallbackReachable).toBe(true);
    expect(audience.headline).toBe("On for every group.");
    expect(audience.bucketing).toBe("group");
  });

  it("describes device bucketing and keeps its fallback reachable", () => {
    const audience = shapeFlagAudience(
      flagWith({
        bucketing_identifier: "device_id",
        groups: [{ rollout_percentage: 100 }],
      }),
    );

    expect(audience.fallbackReachable).toBe(true);
    expect(audience.headline).toBe("On for every device.");
    expect(audience.bucketing).toBe("device");
  });

  it("surfaces the enrollment key for early access flags", () => {
    const audience = shapeFlagAudience(
      flagWith({
        feature_enrollment: true,
        groups: [{ rollout_percentage: 100 }],
      }),
    );

    expect(audience.enrollmentKey).toBe("$feature_enrollment/test-flag");
  });

  it("surfaces the experiment holdout", () => {
    const audience = shapeFlagAudience(
      flagWith({
        holdout: { id: 3, exclusion_percentage: 20 },
        groups: [{ rollout_percentage: 100 }],
      }),
    );

    expect(audience.holdout).toEqual({ id: "3", exclusionPercentage: 20 });
  });

  it("does not describe a fraction of a named person at partial rollout", () => {
    const people = new Map([
      ["u-1", { uuid: "p-1", name: "Alex", email: null }],
    ]);
    const audience = shapeFlagAudience(
      flagWith({
        groups: [
          {
            properties: [
              {
                type: "person",
                key: "distinct_id",
                operator: "exact",
                value: "u-1",
              },
            ],
            rollout_percentage: 25,
          },
        ],
      }),
      people,
    );

    expect(audience.headline).toBe("On for Alex.");
  });

  it("does not label excluded distinct IDs as targeted", () => {
    const flag = flagWith({
      groups: [
        {
          properties: [
            {
              type: "person",
              key: "distinct_id",
              operator: "is_not",
              value: "bot-1",
            },
          ],
          rollout_percentage: 100,
        },
      ],
    });

    // Person-name resolution still collects the excluded id, but the
    // targeted-ids field must not claim the rule targets it.
    expect(targetedDistinctIds(flag)).toEqual(["bot-1"]);
    expect(targetedDistinctIds(flag, true)).toEqual([]);
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
