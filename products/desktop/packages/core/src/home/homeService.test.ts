import { describe, expect, it, vi } from "vitest";
import type { ProjectApiClient } from "../canvas/projectApiClient";
import { HomeService } from "./homeService";

function apiFlag(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    key: "new-checkout",
    name: "The rebuilt checkout",
    active: true,
    filters: { groups: [{ rollout_percentage: 25 }] },
    experiment_set: [],
    created_by: { id: 7, first_name: "Ada", last_name: "L" },
    created_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

function apiExperiment(overrides: Record<string, unknown> = {}) {
  return {
    id: 11,
    name: "Checkout copy",
    description: "Shorter labels",
    feature_flag_key: "new-checkout",
    status: "running",
    start_date: "2026-07-02T00:00:00Z",
    end_date: null,
    parameters: {
      feature_flag_variants: [{ key: "control" }, { key: "test" }],
    },
    created_by: { id: 7, first_name: "Ada" },
    created_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

/** A ProjectApiClient whose `json` is resolved per path prefix. */
function fakeApi(
  handlers: Record<string, { results?: unknown[] } | Error>,
): ProjectApiClient {
  return {
    json: vi.fn(async (path: string) => {
      const key = Object.keys(handlers).find((prefix) =>
        path.startsWith(prefix),
      );
      if (key === undefined) throw new Error(`Unhandled path: ${path}`);
      const handler = handlers[key];
      if (handler instanceof Error) throw handler;
      return handler;
    }),
  } as unknown as ProjectApiClient;
}

describe("HomeService.work", () => {
  it("normalizes both groups and marks the viewer's own rows", async () => {
    const service = new HomeService(
      fakeApi({
        "feature_flags/": { results: [apiFlag()] },
        "experiments/": { results: [apiExperiment()] },
      }),
    );

    const work = await service.work({ viewerId: 7, limit: 6 });

    expect(work.featureFlags).toEqual([
      {
        id: 1,
        key: "new-checkout",
        name: "The rebuilt checkout",
        active: true,
        rolloutPercentage: 25,
        hasExperiment: false,
        createdAt: Date.parse("2026-07-01T00:00:00Z"),
        yours: true,
        createdBy: "Ada L",
      },
    ]);
    expect(work.experiments).toEqual([
      {
        id: 11,
        name: "Checkout copy",
        description: "Shorter labels",
        featureFlagKey: "new-checkout",
        stage: "running",
        startedAt: Date.parse("2026-07-02T00:00:00Z"),
        endedAt: null,
        variants: ["control", "test"],
        yours: true,
        createdBy: "Ada",
      },
    ]);
    expect(work.unavailable).toEqual([]);
  });

  it("reports a group the token cannot read instead of failing the call", async () => {
    const service = new HomeService(
      fakeApi({
        "feature_flags/": { results: [apiFlag()] },
        "experiments/": new Error("Failed to list experiments (403)"),
      }),
    );

    const work = await service.work({ viewerId: 7, limit: 6 });

    expect(work.featureFlags).toHaveLength(1);
    expect(work.experiments).toEqual([]);
    expect(work.unavailable).toEqual(["experiments"]);
  });

  it("leads with running experiments, then the viewer's own, then the newest", async () => {
    const service = new HomeService(
      fakeApi({
        "feature_flags/": { results: [] },
        "experiments/": {
          results: [
            apiExperiment({ id: 1, status: "draft", created_by: { id: 9 } }),
            apiExperiment({ id: 2, status: "stopped" }),
            apiExperiment({ id: 3, status: "exposure_frozen" }),
            apiExperiment({ id: 4, status: "paused", created_by: { id: 9 } }),
          ],
        },
      }),
    );

    const work = await service.work({ viewerId: 7, limit: 6 });

    expect(work.experiments.map((e) => [e.id, e.stage])).toEqual([
      [3, "running"],
      [4, "paused"],
      [1, "draft"],
      [2, "concluded"],
    ]);
  });

  it("keeps only `limit` rows per group", async () => {
    const service = new HomeService(
      fakeApi({
        "feature_flags/": {
          results: [
            apiFlag({ id: 1, key: "a" }),
            apiFlag({ id: 2, key: "b" }),
            apiFlag({ id: 3, key: "c" }),
          ],
        },
        "experiments/": { results: [] },
      }),
    );

    const work = await service.work({ viewerId: null, limit: 2 });

    expect(work.featureFlags.map((flag) => flag.key)).toEqual(["a", "b"]);
    expect(work.featureFlags.every((flag) => !flag.yours)).toBe(true);
  });
});
