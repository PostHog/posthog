import type { DismissalReasonOptionValue } from "@posthog/shared";

export interface BulkActionResult {
  successCount: number;
  failureCount: number;
}

export interface DismissReportInput {
  reason: DismissalReasonOptionValue;
  note: string;
  /** 'owner/repo' the reports should have targeted; only set when reason is 'wrong_repo'. */
  correctedRepository?: string | null;
}

export type SuppressStateRequest = {
  state: "suppressed";
  dismissal_reason?: DismissalReasonOptionValue;
  dismissal_note?: string;
  corrected_repository?: string;
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
    // The API rejects corrected_repository with any other reason, so the gate lives here
    // rather than in every caller that builds a DismissReportInput.
    ...(dismissal.reason === "wrong_repo" && dismissal.correctedRepository
      ? { corrected_repository: dismissal.correctedRepository }
      : {}),
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
