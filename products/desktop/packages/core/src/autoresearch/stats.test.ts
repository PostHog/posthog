import { describe, expect, it } from "vitest";
import type { AutoresearchIteration, AutoresearchRun } from "./schemas";
import {
  computeBest,
  evaluateContinuation,
  getAutoresearchElapsedMs,
  isImprovement,
  meetsTarget,
  summarizeRun,
} from "./stats";

function iteration(
  index: number,
  value: number,
  overrides: Partial<AutoresearchIteration> = {},
): AutoresearchIteration {
  return {
    index,
    value,
    bestValue: value,
    delta: null,
    summary: null,
    hypothesis: null,
    plan: null,
    approach: null,
    at: 1000 + index,
    ...overrides,
  };
}

function makeRun(overrides: {
  iterations?: AutoresearchIteration[];
  direction?: "maximize" | "minimize";
  targetValue?: number | null;
  maxIterations?: number;
  startedAt?: number;
  pausedAt?: number | null;
  pausedDurationMs?: number;
  pauseIntervals?: AutoresearchRun["pauseIntervals"];
  endedAt?: number | null;
}): AutoresearchRun {
  return {
    id: "ar-1",
    config: {
      taskId: "task-1",
      direction: overrides.direction ?? "maximize",
      targetValue: overrides.targetValue ?? null,
      maxIterations: overrides.maxIterations ?? 10,
      implementModel: null,
      measureModel: null,
      implementEffort: null,
      measureEffort: null,
      instructions: "Improve the score.",
    },
    status: "running",
    metricName: "score",
    metricUnit: null,
    phase: null,
    originalModel: null,
    originalEffort: null,
    researchFindings: [],
    iterations: overrides.iterations ?? [],
    startedAt: overrides.startedAt ?? 0,
    pausedAt: overrides.pausedAt,
    pausedDurationMs: overrides.pausedDurationMs,
    pauseIntervals: overrides.pauseIntervals ?? [],
    endedAt: overrides.endedAt ?? null,
    endReason: null,
    interruptedReason: null,
    lastError: null,
  };
}

describe("getAutoresearchElapsedMs", () => {
  it("freezes while paused and excludes completed pause intervals", () => {
    expect(
      getAutoresearchElapsedMs(
        makeRun({ startedAt: 1_000, pausedAt: 11_000 }),
        31_000,
      ),
    ).toBe(10_000);
    expect(
      getAutoresearchElapsedMs(
        makeRun({ startedAt: 1_000, pausedDurationMs: 20_000 }),
        36_000,
      ),
    ).toBe(15_000);
    expect(
      getAutoresearchElapsedMs(
        makeRun({
          startedAt: 1_000,
          pauseIntervals: [{ startedAt: 11_000, endedAt: 31_000 }],
        }),
        36_000,
      ),
    ).toBe(15_000);
  });
});

describe("isImprovement", () => {
  it.each([
    ["maximize", 5, 3, true],
    ["maximize", 3, 5, false],
    ["maximize", 5, 5, false],
    ["minimize", 3, 5, true],
    ["minimize", 5, 3, false],
    ["minimize", 5, 5, false],
  ] as const)(
    "%s: candidate %d vs reference %d -> %s",
    (direction, candidate, reference, expected) => {
      expect(isImprovement(candidate, reference, direction)).toBe(expected);
    },
  );

  it("treats a null reference as an improvement", () => {
    expect(isImprovement(1, null, "maximize")).toBe(true);
    expect(isImprovement(1, null, "minimize")).toBe(true);
  });
});

describe("meetsTarget", () => {
  it.each([
    ["maximize", 10, 10, true],
    ["maximize", 11, 10, true],
    ["maximize", 9, 10, false],
    ["minimize", 10, 10, true],
    ["minimize", 9, 10, true],
    ["minimize", 11, 10, false],
  ] as const)(
    "%s: value %d vs target %d -> %s",
    (direction, value, target, expected) => {
      expect(meetsTarget(value, target, direction)).toBe(expected);
    },
  );

  it("never meets a null target", () => {
    expect(meetsTarget(Number.MAX_VALUE, null, "maximize")).toBe(false);
  });
});

describe("computeBest", () => {
  it("returns null for no iterations", () => {
    expect(computeBest([], "maximize")).toBeNull();
  });

  it("finds the highest value when maximizing", () => {
    const best = computeBest(
      [iteration(1, 3), iteration(2, 7), iteration(3, 5)],
      "maximize",
    );
    expect(best).toEqual({ value: 7, index: 2 });
  });

  it("finds the lowest value when minimizing", () => {
    const best = computeBest(
      [iteration(1, 3), iteration(2, 7), iteration(3, 2)],
      "minimize",
    );
    expect(best).toEqual({ value: 2, index: 3 });
  });

  it("keeps the earliest iteration on ties", () => {
    const best = computeBest([iteration(1, 5), iteration(2, 5)], "maximize");
    expect(best).toEqual({ value: 5, index: 1 });
  });
});

describe("evaluateContinuation", () => {
  it("continues while under budget with no target", () => {
    const run = makeRun({ iterations: [iteration(1, 5)] });
    expect(evaluateContinuation(run)).toEqual({ done: false });
  });

  it("completes when the latest value reaches the target", () => {
    const run = makeRun({
      iterations: [iteration(1, 5), iteration(2, 12)],
      targetValue: 10,
    });
    expect(evaluateContinuation(run)).toEqual({
      done: true,
      reason: "target-reached",
    });
  });

  it("only the latest iteration counts toward the target", () => {
    const run = makeRun({
      iterations: [iteration(1, 12), iteration(2, 5)],
      targetValue: 10,
    });
    expect(evaluateContinuation(run)).toEqual({ done: false });
  });

  it("completes when the iteration budget is spent", () => {
    const run = makeRun({
      iterations: [iteration(1, 1), iteration(2, 2)],
      maxIterations: 2,
    });
    expect(evaluateContinuation(run)).toEqual({
      done: true,
      reason: "max-iterations",
    });
  });

  it("prefers target-reached when both conditions hold", () => {
    const run = makeRun({
      iterations: [iteration(1, 1), iteration(2, 20)],
      maxIterations: 2,
      targetValue: 10,
    });
    expect(evaluateContinuation(run)).toEqual({
      done: true,
      reason: "target-reached",
    });
  });

  it("does not complete an empty run", () => {
    expect(evaluateContinuation(makeRun({}))).toEqual({ done: false });
  });
});

describe("summarizeRun", () => {
  it("summarizes an empty run", () => {
    const summary = summarizeRun(makeRun({}));
    expect(summary).toEqual({
      iterationCount: 0,
      best: null,
      last: null,
      improvementFromBaseline: null,
      improvedIterationCount: 0,
    });
  });

  it("computes best, last, and baseline improvement", () => {
    const iterations = [iteration(1, 100), iteration(2, 80), iteration(3, 90)];
    const summary = summarizeRun(
      makeRun({ iterations, direction: "minimize" }),
    );
    expect(summary.iterationCount).toBe(3);
    expect(summary.best).toEqual({ value: 80, index: 2 });
    expect(summary.last?.value).toBe(90);
    expect(summary.improvementFromBaseline).toBe(-20);
  });

  it("counts improvements excluding the baseline iteration", () => {
    const iterations = [
      iteration(1, 10),
      iteration(2, 12),
      iteration(3, 11),
      iteration(4, 15),
    ];
    const summary = summarizeRun(
      makeRun({ iterations, direction: "maximize" }),
    );
    expect(summary.improvedIterationCount).toBe(2);
  });
});
