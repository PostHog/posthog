import type { ScoutConfig, ScoutRun } from "@posthog/api-client/posthog-client";
import { computeScoutRollups } from "@posthog/core/scouts/scoutPresentation";
import { describe, expect, it } from "vitest";
import {
  describeLastRun,
  formatRate,
  intervalOptions,
  lifecycleBadgeClasses,
  runsWindowHasRunningRun,
} from "./scoutRows";

const NOW = new Date("2026-01-02T12:00:00.000Z");

function run(overrides: Partial<ScoutRun> = {}): ScoutRun {
  return {
    run_id: "run-1",
    skill_name: "signals-scout-errors",
    skill_version: 1,
    status: "completed",
    started_at: "2026-01-02T11:00:00.000Z",
    completed_at: "2026-01-02T11:05:00.000Z",
    task_id: null,
    task_run_id: null,
    task_url: null,
    summary: "",
    emitted_count: 0,
    emitted_finding_ids: [],
    ...overrides,
  };
}

function config(overrides: Partial<ScoutConfig> = {}): ScoutConfig {
  return {
    id: "config-1",
    skill_name: "signals-scout-errors",
    enabled: true,
    emit: true,
    run_interval_minutes: 60,
    last_run_at: null,
    created_at: "2026-01-01T00:00:00.000Z",
    ...overrides,
  };
}

describe("formatRate", () => {
  it.each([
    { rate: 1, expected: "100%" },
    { rate: 0.815, expected: "82%" },
    { rate: 0, expected: "0%" },
    { rate: null, expected: "—" },
    { rate: undefined, expected: "—" },
  ])("renders $rate as $expected", ({ rate, expected }) => {
    expect(formatRate(rate)).toBe(expected);
  });
});

describe("runsWindowHasRunningRun", () => {
  it.each([
    {
      name: "a running run",
      runs: [run({ status: "in_progress", completed_at: null })],
      expected: true,
    },
    { name: "only finished runs", runs: [run()], expected: false },
    { name: "no runs at all", runs: [] as ScoutRun[], expected: false },
  ])("is $expected for $name", ({ runs, expected }) => {
    expect(
      runsWindowHasRunningRun(
        { runs, complete: true },
        computeScoutRollups(runs),
      ),
    ).toBe(expected);
  });

  it("is false while the window has not loaded", () => {
    expect(runsWindowHasRunningRun(undefined, new Map())).toBe(false);
  });
});

describe("describeLastRun", () => {
  it("returns null when the scout has no run in the window", () => {
    expect(describeLastRun(undefined, NOW)).toBeNull();
  });

  it("summarises the newest run and timestamps it by completion", () => {
    const rollups = computeScoutRollups([
      run({ run_id: "old", started_at: "2026-01-02T09:00:00.000Z" }),
      run({
        run_id: "new",
        started_at: "2026-01-02T11:00:00.000Z",
        completed_at: "2026-01-02T11:05:00.000Z",
        emitted_count: 3,
      }),
    ]);

    const summary = describeLastRun(rollups.get("signals-scout-errors"), NOW);

    expect(summary).toEqual({
      label: "3 signals emitted",
      at: new Date("2026-01-02T11:05:00.000Z").getTime(),
      isRunning: false,
    });
  });

  it("falls back to the start time and flags a run still in flight", () => {
    const rollups = computeScoutRollups([
      run({
        status: "in_progress",
        started_at: "2026-01-02T11:50:00.000Z",
        completed_at: null,
      }),
    ]);

    expect(describeLastRun(rollups.get("signals-scout-errors"), NOW)).toEqual({
      label: "running now",
      at: new Date("2026-01-02T11:50:00.000Z").getTime(),
      isRunning: true,
    });
  });

  it("still counts a run stuck past the deadline as running", () => {
    const rollups = computeScoutRollups([
      run({
        status: "in_progress",
        started_at: "2026-01-02T11:00:00.000Z",
        completed_at: null,
      }),
    ]);

    expect(describeLastRun(rollups.get("signals-scout-errors"), NOW)).toEqual({
      label: "running past the deadline – may be stuck",
      at: new Date("2026-01-02T11:00:00.000Z").getTime(),
      isRunning: true,
    });
  });

  it("has no timestamp when the run never started", () => {
    const rollups = computeScoutRollups([
      run({ status: "queued", started_at: null, completed_at: null }),
    ]);

    expect(describeLastRun(rollups.get("signals-scout-errors"), NOW)?.at).toBe(
      null,
    );
  });
});

describe("intervalOptions", () => {
  it("offers the shared presets for a scout already on one", () => {
    const options = intervalOptions(config({ run_interval_minutes: 60 }));

    expect(options.map((option) => option.value)).toEqual([
      "30",
      "60",
      "120",
      "180",
      "360",
      "720",
      "1440",
    ]);
  });

  it("appends the scout's own cadence when it is not a preset", () => {
    const options = intervalOptions(config({ run_interval_minutes: 45 }));

    expect(options.at(-1)).toEqual({
      value: "45",
      label: "Every 45 minutes",
    });
  });
});

describe("lifecycleBadgeClasses", () => {
  it.each([
    { lifecycle: "paused_by_system" as const, hasBadge: true },
    { lifecycle: "warned" as const, hasBadge: true },
    { lifecycle: "active" as const, hasBadge: false },
    { lifecycle: "paused_by_user" as const, hasBadge: false },
  ])("$lifecycle has a badge: $hasBadge", ({ lifecycle, hasBadge }) => {
    expect(lifecycleBadgeClasses(lifecycle) !== null).toBe(hasBadge);
  });
});
