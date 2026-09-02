import type {
  DismissalReasonOptionValue,
  ResolveReasonOptionValue,
} from "@posthog/shared";

export interface BulkActionResult {
  successCount: number;
  failureCount: number;
}

export interface DismissReportInput {
  reason: DismissalReasonOptionValue;
  note: string;
}

export type SuppressStateRequest = {
  state: "suppressed";
  dismissal_reason?: DismissalReasonOptionValue;
  dismissal_note?: string;
};

/** Body for `updateSignalReportState` when suppressing/dismissing. Notes are clamped to 4000 chars. */
export function buildSuppressRequest(
  dismissal?: DismissReportInput,
): SuppressStateRequest {
  if (!dismissal) {
    return { state: "suppressed" };
  }
  return {
    state: "suppressed",
    dismissal_reason: dismissal.reason,
    dismissal_note: dismissal.note.slice(0, 4000),
  };
}

export type SnoozeStateRequest = {
  state: "potential";
  snooze_for: number;
  dismissal_reason?: DismissalReasonOptionValue;
  dismissal_note?: string;
};

/**
 * Body for `updateSignalReportState` when snoozing. Carries the dismiss reason and
 * note when one drove the snooze (e.g. "Already fixed"); a plain snooze sends neither.
 * Notes are clamped to 4000 chars.
 */
export function buildSnoozeRequest(
  dismissal?: DismissReportInput,
): SnoozeStateRequest {
  if (!dismissal) {
    return { state: "potential", snooze_for: 1 };
  }
  return {
    state: "potential",
    snooze_for: 1,
    dismissal_reason: dismissal.reason,
    dismissal_note: dismissal.note.slice(0, 4000),
  };
}

export type ResolveStateRequest = {
  state: "resolved";
  dismissal_reason: ResolveReasonOptionValue;
  dismissal_note?: string;
};

export function buildResolveRequest(
  reason: ResolveReasonOptionValue,
  note: string,
): ResolveStateRequest {
  const trimmedNote = note.trim().slice(0, 4000);
  return {
    state: "resolved",
    dismissal_reason: reason,
    ...(trimmedNote ? { dismissal_note: trimmedNote } : {}),
  };
}

/** Tally `Promise.allSettled` results into a success/failure count. */
export function tallySettledResults(
  results: PromiseSettledResult<unknown>[],
): BulkActionResult {
  const successCount = results.filter(
    (result) => result.status === "fulfilled",
  ).length;
  return {
    successCount,
    failureCount: results.length - successCount,
  };
}
