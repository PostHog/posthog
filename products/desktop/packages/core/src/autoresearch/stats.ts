/**
 * Pure decision and aggregation functions over autoresearch runs.
 * No side effects, no store access.
 */
import type {
  AutoresearchDirection,
  AutoresearchEndReason,
  AutoresearchIteration,
  AutoresearchRun,
} from "./schemas";

export function getAutoresearchElapsedMs(
  run: AutoresearchRun,
  now: number,
): number {
  const effectiveEnd = run.endedAt ?? run.pausedAt ?? now;
  const trackedPausedDurationMs = (run.pauseIntervals ?? []).reduce(
    (total, interval) => {
      const overlapStart = Math.max(run.startedAt, interval.startedAt);
      const overlapEnd = Math.min(effectiveEnd, interval.endedAt);
      return total + Math.max(0, overlapEnd - overlapStart);
    },
    0,
  );
  const pausedDurationMs = Math.max(
    trackedPausedDurationMs,
    run.pausedDurationMs ?? 0,
  );
  return Math.max(0, effectiveEnd - run.startedAt - pausedDurationMs);
}

export function isImprovement(
  candidate: number,
  reference: number | null,
  direction: AutoresearchDirection,
): boolean {
  if (reference === null) return true;
  return direction === "maximize"
    ? candidate > reference
    : candidate < reference;
}

export function meetsTarget(
  value: number,
  targetValue: number | null,
  direction: AutoresearchDirection,
): boolean {
  if (targetValue === null) return false;
  return direction === "maximize" ? value >= targetValue : value <= targetValue;
}

export function computeBest(
  iterations: AutoresearchIteration[],
  direction: AutoresearchDirection,
): { value: number; index: number } | null {
  let best: { value: number; index: number } | null = null;
  for (const iteration of iterations) {
    if (isImprovement(iteration.value, best?.value ?? null, direction)) {
      best = { value: iteration.value, index: iteration.index };
    }
  }
  return best;
}

export type ContinuationDecision =
  | { done: false }
  | {
      done: true;
      reason: Extract<
        AutoresearchEndReason,
        "target-reached" | "max-iterations"
      >;
    };

/**
 * Decide whether a run should keep iterating after its latest iteration.
 * Target takes precedence over the iteration budget.
 */
export function evaluateContinuation(
  run: AutoresearchRun,
): ContinuationDecision {
  const last = run.iterations[run.iterations.length - 1];
  if (
    last &&
    meetsTarget(last.value, run.config.targetValue, run.config.direction)
  ) {
    return { done: true, reason: "target-reached" };
  }
  if (run.iterations.length >= run.config.maxIterations) {
    return { done: true, reason: "max-iterations" };
  }
  return { done: false };
}

export interface RunSummary {
  iterationCount: number;
  best: { value: number; index: number } | null;
  last: AutoresearchIteration | null;
  /** Signed change from the first iteration's value to the best value. */
  improvementFromBaseline: number | null;
  improvedIterationCount: number;
}

export function summarizeRun(run: AutoresearchRun): RunSummary {
  const { iterations } = run;
  const direction = run.config.direction;
  const best = computeBest(iterations, direction);
  const last = iterations[iterations.length - 1] ?? null;
  const baseline = iterations[0] ?? null;

  let improvedIterationCount = 0;
  let runningBest: number | null = null;
  for (const iteration of iterations) {
    if (isImprovement(iteration.value, runningBest, direction)) {
      if (runningBest !== null) improvedIterationCount++;
      runningBest = iteration.value;
    }
  }

  return {
    iterationCount: iterations.length,
    best,
    last,
    improvementFromBaseline:
      best && baseline ? best.value - baseline.value : null,
    improvedIterationCount,
  };
}
