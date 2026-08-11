import type { DismissalReasonOptionValue } from "@posthog/shared";
import type { SignalReport } from "@posthog/shared/domain-types";
import { inboxStatusLabel } from "./statusLabels";

export type BulkActionName = "suppress" | "snooze" | "delete" | "reingest";

export interface BulkActionResult {
  successCount: number;
  failureCount: number;
}

/** Active workflow statuses for snooze and suppress. Terminal `suppressed` / `deleted` are excluded. */
export const suppressibleStatuses = new Set<SignalReport["status"]>([
  "potential",
  "candidate",
  "in_progress",
  "pending_input",
  "ready",
  "failed",
]);

/** Clause after "Disabled because …" (see `@components/ui/Button`). */
export const DISABLED_NO_SELECTION = "you haven't selected a report";

/** Statuses that block suppression; labels match `inboxStatusLabel`. */
export const SUPPRESS_BLOCKED_STATUS_PHRASE = (
  ["suppressed", "deleted"] as const satisfies readonly SignalReport["status"][]
)
  .map((status) => inboxStatusLabel(status))
  .join(" or ");

export interface SelectedReportEligibility {
  selectedReports: SignalReport[];
  selectedIds: string[];
  selectedCount: number;
  snoozeDisabledReason: string | null;
  suppressDisabledReason: string | null;
  deleteDisabledReason: string | null;
  reingestDisabledReason: string | null;
}

export function formatBulkActionSummary(
  action: BulkActionName,
  result: BulkActionResult,
): string {
  const { successCount, failureCount } = result;
  const pluralized = successCount === 1 ? "report" : "reports";
  const formulated =
    action === "suppress"
      ? `${pluralized} dismissed`
      : action === "snooze"
        ? `${pluralized} snoozed`
        : action === "delete"
          ? `${pluralized} deleted`
          : `${pluralized} reingested`;
  if (failureCount === 0) {
    return `${successCount} ${formulated}`;
  }
  return `${successCount} ${formulated}, ${failureCount} failed`;
}

export function getSnoozeOrSuppressDisabledReason(
  selectedCount: number,
  selectedReports: SignalReport[],
): string | null {
  if (selectedCount === 0) {
    return DISABLED_NO_SELECTION;
  }
  const ok = selectedReports.every((report) =>
    suppressibleStatuses.has(report.status),
  );
  if (ok) {
    return null;
  }
  return `every selected report must not already be ${SUPPRESS_BLOCKED_STATUS_PHRASE}`;
}

export function getSelectedReportEligibility(
  reports: SignalReport[],
  selectedIds: string[],
): SelectedReportEligibility {
  const selectedIdSet = new Set(selectedIds);
  const selectedReports = reports.filter((report) =>
    selectedIdSet.has(report.id),
  );
  const selectedCount = selectedReports.length;

  const snoozeOrSuppressDisabledReason = getSnoozeOrSuppressDisabledReason(
    selectedCount,
    selectedReports,
  );

  return {
    selectedReports,
    selectedIds: selectedReports.map((report) => report.id),
    selectedCount,
    snoozeDisabledReason: snoozeOrSuppressDisabledReason,
    suppressDisabledReason: snoozeOrSuppressDisabledReason,
    deleteDisabledReason: selectedCount === 0 ? DISABLED_NO_SELECTION : null,
    reingestDisabledReason: selectedCount === 0 ? DISABLED_NO_SELECTION : null,
  };
}

/** Toolbar: selected report ids. Dismiss dialog: that report's id, or null when closed. */
export type InboxBulkSelection = string[] | string | null;

const emptyBulkIds: string[] = [];

export function effectiveBulkIdsFromSelection(
  selection: InboxBulkSelection,
): string[] {
  if (selection == null) {
    return emptyBulkIds;
  }
  if (Array.isArray(selection)) {
    return selection;
  }
  return [selection];
}

export function bulkSelectionKey(selection: InboxBulkSelection): string {
  if (selection == null) {
    return "";
  }
  if (Array.isArray(selection)) {
    return selection.join("\0");
  }
  return selection;
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
