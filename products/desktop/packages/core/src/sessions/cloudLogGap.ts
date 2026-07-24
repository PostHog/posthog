import type { StoredLogEntry } from "@posthog/shared";

/**
 * Pure logic for reconciling cloud session log gaps. The session service owns
 * the I/O (fetching logs, writing the store); this module owns the decisions:
 * how to coalesce overlapping reconcile requests, and — given the counts a
 * fetch returned — what the service should do next.
 */

export interface CloudLogGapReconcileRequest {
  taskId: string;
  taskRunId: string;
  expectedCount: number;
  currentCount: number;
  newEntries: StoredLogEntry[];
  logUrl?: string;
}

export interface CloudLogGapDeficiency {
  expectedCount: number;
  observedLineCount: number;
}

/**
 * Coalesce a queued reconcile request with a newer one, widening the range to
 * cover both (lowest currentCount, highest expectedCount) and concatenating
 * their entries so no observed event is dropped.
 */
export function mergeCloudLogGapRequests(
  current: CloudLogGapReconcileRequest | undefined,
  next: CloudLogGapReconcileRequest,
): CloudLogGapReconcileRequest {
  if (!current) return next;

  return {
    taskId: next.taskId,
    taskRunId: next.taskRunId,
    currentCount: Math.min(current.currentCount, next.currentCount),
    expectedCount: Math.max(current.expectedCount, next.expectedCount),
    newEntries: [...current.newEntries, ...next.newEntries],
    logUrl: next.logUrl ?? current.logUrl,
  };
}

export type CloudLogAppendPlan =
  | { kind: "caught-up" }
  | { kind: "append-tail"; tailCount: number }
  | { kind: "gap" };

/**
 * Decide how to apply a batch of streamed cloud log entries, given how many
 * lines the store has already committed (`currentLineCount`), how many the
 * update claims should exist (`expectedLineCount`), and how many entries the
 * update actually carried (`availableEntryCount`):
 * - `caught-up`: the store already has everything; drop the batch.
 * - `append-tail`: append only the last `tailCount` entries (the batch covers
 *   the gap; earlier entries are duplicates already in the store).
 * - `gap`: the batch cannot cover the gap; fall back to a reconcile fetch.
 *
 * Boundary: when `delta === availableEntryCount` the whole batch is the tail,
 * so it is still an `append-tail`, not a `gap`.
 */
export function classifyCloudLogAppend(
  currentLineCount: number,
  expectedLineCount: number,
  availableEntryCount: number,
): CloudLogAppendPlan {
  const delta = expectedLineCount - currentLineCount;
  if (delta <= 0) {
    return { kind: "caught-up" };
  }
  if (delta <= availableEntryCount) {
    return { kind: "append-tail", tailCount: delta };
  }
  return { kind: "gap" };
}

export type CloudLogGapAction =
  | { kind: "already-current" }
  | { kind: "fill"; processedLineCount: number }
  | {
      kind: "commit-best-effort";
      processedLineCount: number;
      reason: "parse-failure" | "stable-deficit";
    }
  | { kind: "wait"; deficiency: CloudLogGapDeficiency };

export interface CloudLogGapInput {
  /** Entry count the latest cloud update claims should exist. */
  expectedCount: number;
  /** Entries already committed to the store for this run. */
  latestCount: number;
  /** Entries the just-completed fetch actually parsed. */
  totalLineCount: number;
  /** Lines the fetch failed to parse (proof of corruption). */
  parseFailureCount: number;
  /** Deficit observed on the previous reconcile pass, if any. */
  previousDeficiency: CloudLogGapDeficiency | undefined;
}

/**
 * Decide what to do after a reconcile fetch:
 * - `already-current`: the store already caught up; drop any tracked deficit.
 * - `fill`: the fetch covered the gap; commit everything it returned.
 * - `commit-best-effort`: the gap is unrecoverable (parse failure or a stable
 *   repeat of the same deficit); commit what we have and stop looping.
 * - `wait`: still short, but likely lag; record the deficit and retry later.
 */
export function classifyCloudLogGap(
  input: CloudLogGapInput,
): CloudLogGapAction {
  const {
    expectedCount,
    latestCount,
    totalLineCount,
    parseFailureCount,
    previousDeficiency,
  } = input;

  if (latestCount >= expectedCount) {
    return { kind: "already-current" };
  }

  if (totalLineCount >= expectedCount) {
    return { kind: "fill", processedLineCount: totalLineCount };
  }

  const sameDeficiencyAsBefore =
    previousDeficiency?.expectedCount === expectedCount &&
    previousDeficiency?.observedLineCount === totalLineCount;

  if (parseFailureCount > 0 || sameDeficiencyAsBefore) {
    return {
      kind: "commit-best-effort",
      processedLineCount: expectedCount,
      reason: parseFailureCount > 0 ? "parse-failure" : "stable-deficit",
    };
  }

  return {
    kind: "wait",
    deficiency: { expectedCount, observedLineCount: totalLineCount },
  };
}
