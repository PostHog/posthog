import { describe, expect, test } from "vitest";
import { classifyStaleness } from "./stale-flags.js";
import type { Experiment, FeatureFlag } from "./types.js";

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

function makeExperiment(overrides: Partial<Experiment> = {}): Experiment {
  return {
    id: 1,
    name: "Test Experiment",
    description: null,
    start_date: "2024-01-01",
    end_date: null,
    feature_flag_key: "test-flag",
    created_at: "2024-01-01",
    created_by: null,
    ...overrides,
  };
}

describe("classifyStaleness", () => {
  test("returns not_in_posthog when flag is undefined", () => {
    expect(classifyStaleness("unknown-flag", undefined, [])).toBe(
      "not_in_posthog",
    );
  });

  test("returns inactive when flag is not active", () => {
    const flag = makeFlag({ active: false });
    expect(classifyStaleness("test-flag", flag, [])).toBe("inactive");
  });

  test("returns experiment_complete when linked experiment has end_date", () => {
    const flag = makeFlag({ active: true });
    const experiment = makeExperiment({ end_date: "2024-06-01" });
    expect(classifyStaleness("test-flag", flag, [experiment])).toBe(
      "experiment_complete",
    );
  });

  test("returns null when experiment is still running", () => {
    const flag = makeFlag({ active: true });
    const experiment = makeExperiment({ end_date: null });
    expect(classifyStaleness("test-flag", flag, [experiment])).toBe(null);
  });

  test("returns fully_rolled_out for 100% rollout old flag", () => {
    const flag = makeFlag({
      active: true,
      created_at: "2020-01-01",
      filters: { groups: [{ rollout_percentage: 100, properties: [] }] },
    });
    expect(classifyStaleness("test-flag", flag, [])).toBe("fully_rolled_out");
  });

  test("returns null for 100% rollout recent flag (within age threshold)", () => {
    const flag = makeFlag({
      active: true,
      created_at: new Date().toISOString(),
      filters: { groups: [{ rollout_percentage: 100, properties: [] }] },
    });
    expect(classifyStaleness("test-flag", flag, [])).toBe(null);
  });

  test("returns null for active flag with partial rollout", () => {
    const flag = makeFlag({
      active: true,
      filters: { groups: [{ rollout_percentage: 50, properties: [] }] },
    });
    expect(classifyStaleness("test-flag", flag, [])).toBe(null);
  });

  test("respects custom staleFlagAgeDays", () => {
    const flag = makeFlag({
      active: true,
      created_at: new Date(Date.now() - 10 * 86_400_000).toISOString(), // 10 days ago
      filters: { groups: [{ rollout_percentage: 100, properties: [] }] },
    });
    // With 30-day threshold, not stale yet
    expect(
      classifyStaleness("test-flag", flag, [], { staleFlagAgeDays: 30 }),
    ).toBe(null);
    // With 5-day threshold, stale
    expect(
      classifyStaleness("test-flag", flag, [], { staleFlagAgeDays: 5 }),
    ).toBe("fully_rolled_out");
  });
});
