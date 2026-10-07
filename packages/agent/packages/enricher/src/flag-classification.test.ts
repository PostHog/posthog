import { describe, expect, test } from "vitest";
import {
  classifyFlagType,
  extractConditionCount,
  extractRollout,
  extractVariants,
  isFullyRolledOut,
} from "./flag-classification.js";
import type { FeatureFlag } from "./types.js";

function makeFlag(overrides: Partial<FeatureFlag> = {}): FeatureFlag {
  return {
    id: 1,
    key: "test-flag",
    name: "Test",
    active: true,
    filters: {},
    created_at: "2024-01-01",
    created_by: null,
    deleted: false,
    ...overrides,
  };
}

describe("classifyFlagType", () => {
  test("undefined flag returns boolean", () => {
    expect(classifyFlagType(undefined)).toBe("boolean");
  });

  test("flag with multivariate variants returns multivariate", () => {
    const flag = makeFlag({
      filters: {
        multivariate: {
          variants: [
            { key: "control", rollout_percentage: 50 },
            { key: "test", rollout_percentage: 50 },
          ],
        },
      },
    });
    expect(classifyFlagType(flag)).toBe("multivariate");
  });

  test("flag with payloads (no multivariate) returns remote_config", () => {
    const flag = makeFlag({
      filters: { payloads: { true: '{"theme":"dark"}' } },
    });
    expect(classifyFlagType(flag)).toBe("remote_config");
  });

  test("flag with neither returns boolean", () => {
    expect(classifyFlagType(makeFlag({ filters: {} }))).toBe("boolean");
  });

  test("empty variants array returns boolean", () => {
    const flag = makeFlag({
      filters: { multivariate: { variants: [] } },
    });
    expect(classifyFlagType(flag)).toBe("boolean");
  });

  test("payloads with all null values returns boolean", () => {
    const flag = makeFlag({
      filters: { payloads: { true: null, false: null } },
    });
    expect(classifyFlagType(flag)).toBe("boolean");
  });

  test("multivariate takes priority over payloads", () => {
    const flag = makeFlag({
      filters: {
        multivariate: {
          variants: [{ key: "control", rollout_percentage: 100 }],
        },
        payloads: { control: '"value"' },
      },
    });
    expect(classifyFlagType(flag)).toBe("multivariate");
  });
});

describe("isFullyRolledOut", () => {
  test("no filters returns false", () => {
    const flag = makeFlag({
      filters: undefined as unknown as Record<string, unknown>,
    });
    expect(isFullyRolledOut(flag)).toBe(false);
  });

  test("empty groups returns false", () => {
    expect(isFullyRolledOut(makeFlag({ filters: { groups: [] } }))).toBe(false);
  });

  test("single group 100% no conditions returns true", () => {
    const flag = makeFlag({
      filters: { groups: [{ rollout_percentage: 100, properties: [] }] },
    });
    expect(isFullyRolledOut(flag)).toBe(true);
  });

  test("100% with conditions returns false", () => {
    const flag = makeFlag({
      filters: {
        groups: [
          {
            rollout_percentage: 100,
            properties: [
              { key: "email", value: "test@example.com", type: "person" },
            ],
          },
        ],
      },
    });
    expect(isFullyRolledOut(flag)).toBe(false);
  });

  test("less than 100% returns false", () => {
    const flag = makeFlag({
      filters: { groups: [{ rollout_percentage: 50, properties: [] }] },
    });
    expect(isFullyRolledOut(flag)).toBe(false);
  });

  test("multiple groups all 100% returns true", () => {
    const flag = makeFlag({
      filters: {
        groups: [
          { rollout_percentage: 100, properties: [] },
          { rollout_percentage: 100, properties: [] },
        ],
      },
    });
    expect(isFullyRolledOut(flag)).toBe(true);
  });

  test("multivariate returns false even with 100% rollout", () => {
    const flag = makeFlag({
      filters: {
        multivariate: {
          variants: [
            { key: "control", rollout_percentage: 50 },
            { key: "test", rollout_percentage: 50 },
          ],
        },
        groups: [{ rollout_percentage: 100, properties: [] }],
      },
    });
    expect(isFullyRolledOut(flag)).toBe(false);
  });

  test("no groups and no multivariate returns false", () => {
    const flag = makeFlag({ filters: {} });
    expect(isFullyRolledOut(flag)).toBe(false);
  });
});

describe("extractRollout", () => {
  test("rollout from groups returns it", () => {
    const flag = makeFlag({
      filters: { groups: [{ rollout_percentage: 75 }] },
    });
    expect(extractRollout(flag)).toBe(75);
  });

  test("rollout in groups returns it", () => {
    const flag = makeFlag({
      filters: { groups: [{ rollout_percentage: 42 }] },
    });
    expect(extractRollout(flag)).toBe(42);
  });

  test("no rollout returns null", () => {
    expect(extractRollout(makeFlag({ filters: {} }))).toBe(null);
  });

  test("first group rollout is returned", () => {
    const flag = makeFlag({
      filters: { groups: [{ rollout_percentage: 60 }] },
    });
    expect(extractRollout(flag)).toBe(60);
  });

  test("rollout 0 returns 0 (not null)", () => {
    const flag = makeFlag({
      filters: { groups: [{ rollout_percentage: 0 }] },
    });
    expect(extractRollout(flag)).toBe(0);
  });
});

describe("extractVariants", () => {
  test("no multivariate returns empty", () => {
    expect(extractVariants(makeFlag({ filters: {} }))).toEqual([]);
  });

  test("multivariate with variants returns them", () => {
    const variants = [
      { key: "control", rollout_percentage: 50 },
      { key: "test", rollout_percentage: 50 },
    ];
    const flag = makeFlag({ filters: { multivariate: { variants } } });
    expect(extractVariants(flag)).toEqual(variants);
  });

  test("empty variants returns empty", () => {
    const flag = makeFlag({ filters: { multivariate: { variants: [] } } });
    expect(extractVariants(flag)).toEqual([]);
  });
});

describe("extractConditionCount", () => {
  test("no groups returns 0", () => {
    expect(extractConditionCount(makeFlag({ filters: {} }))).toBe(0);
  });

  test("groups with empty properties returns 0", () => {
    const flag = makeFlag({
      filters: {
        groups: [
          { properties: [], rollout_percentage: 100 },
          { properties: [], rollout_percentage: 50 },
        ],
      },
    });
    expect(extractConditionCount(flag)).toBe(0);
  });

  test("counts groups with properties", () => {
    const flag = makeFlag({
      filters: {
        groups: [
          {
            properties: [
              { key: "email", value: "@posthog.com", type: "person" },
            ],
          },
          { properties: [] },
          { properties: [{ key: "country", value: "US", type: "person" }] },
        ],
      },
    });
    expect(extractConditionCount(flag)).toBe(2);
  });
});
