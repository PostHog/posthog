import type { DismissalReasonOptionValue } from "@posthog/shared";

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
};

/** Body for `updateSignalReportState` when snoozing. */
export function buildSnoozeRequest(): SnoozeStateRequest {
  return { state: "potential", snooze_for: 1 };
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
