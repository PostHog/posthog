import {
  buildBulkActionEvents,
  type InboxBulkActionType,
} from "@posthog/core/inbox/engagement";
import { inboxStatusLabel } from "@posthog/core/inbox/reportPresentation";
import type { InboxReportActionSurface } from "@posthog/shared/analytics-events";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { SignalReport } from "@posthog/shared/types";
import type { DismissReportDialogResult } from "@posthog/ui/features/inbox/components/DismissReportDialog";
import { reportKeys } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { useInboxReportSelectionStore } from "@posthog/ui/features/inbox/stores/inboxReportSelectionStore";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";

type BulkActionName = "suppress" | "snooze" | "delete" | "reingest";

interface BulkActionResult {
  successCount: number;
  failureCount: number;
  succeededIds: string[];
}

async function runBulkAction(
  reportIds: string[],
  perItem: (reportId: string) => Promise<unknown>,
): Promise<BulkActionResult> {
  const results = await Promise.allSettled(reportIds.map(perItem));
  const succeededIds: string[] = [];
  for (let i = 0; i < results.length; i += 1) {
    if (results[i].status === "fulfilled") {
      succeededIds.push(reportIds[i]);
    }
  }
  return {
    successCount: succeededIds.length,
    failureCount: results.length - succeededIds.length,
    succeededIds,
  };
}

/** Active workflow statuses for snooze and suppress. Terminal `suppressed` / `deleted` are excluded. */
const suppressibleStatuses = new Set<SignalReport["status"]>([
  "potential",
  "candidate",
  "in_progress",
  "pending_input",
  "ready",
  "failed",
]);

/** Clause after "Disabled because …" (see `@posthog/ui/primitives/Button`). */
const DISABLED_NO_SELECTION = "you haven't selected a report";

/** Statuses that block suppression; labels match `inboxStatusLabel`. */
const SUPPRESS_BLOCKED_STATUS_PHRASE = (
  ["suppressed", "deleted"] as const satisfies readonly SignalReport["status"][]
)
  .map((status) => inboxStatusLabel(status))
  .join(" or ");

type SelectedReportEligibility = {
  selectedReports: SignalReport[];
  selectedIds: string[];
  selectedCount: number;
  snoozeDisabledReason: string | null;
  suppressDisabledReason: string | null;
  deleteDisabledReason: string | null;
  reingestDisabledReason: string | null;
};

function formatBulkActionSummary(
  action: BulkActionName,
  result: BulkActionResult,
): string {
  const { successCount, failureCount } = result;
  const pluralized = successCount === 1 ? "report" : "reports";
  const formulated =
    action === "suppress"
      ? `${pluralized} archived`
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

function getSnoozeOrSuppressDisabledReason(
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

function getSelectedReportEligibility(
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

function effectiveBulkIdsFromSelection(
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

/** Snooze disabled reason when `selectedIds` are treated as the bulk selection (matches toolbar logic). */
export function inboxBulkSnoozeDisabledReason(
  reports: SignalReport[],
  selectedIds: string[],
): string | null {
  return getSelectedReportEligibility(reports, selectedIds)
    .snoozeDisabledReason;
}

/** Suppress/dismiss disabled reason when `selectedIds` are treated as the bulk selection. */
export function inboxBulkSuppressDisabledReason(
  reports: SignalReport[],
  selectedIds: string[],
): string | null {
  return getSelectedReportEligibility(reports, selectedIds)
    .suppressDisabledReason;
}

/**
 * Per-report suppress-disabled reason precomputed in one O(N) pass.
 * Cheaper than calling `inboxBulkSuppressDisabledReason(reports, [id])` per
 * card, which collapses to O(N²) when the list rerenders on every keystroke.
 *
 * The disabled-reason depends only on `report.status` here (single-report
 * selection always has count ≥ 1), so we can compute each entry directly
 * without re-running the full eligibility pipeline.
 */
export function buildSuppressDisabledReasonMap(
  reports: SignalReport[],
): Map<string, string | null> {
  const blockedReason = `every selected report must not already be ${SUPPRESS_BLOCKED_STATUS_PHRASE}`;
  const map = new Map<string, string | null>();
  for (const report of reports) {
    map.set(
      report.id,
      suppressibleStatuses.has(report.status) ? null : blockedReason,
    );
  }
  return map;
}

export function useInboxBulkActions(
  reports: SignalReport[],
  selection: InboxBulkSelection,
  surface: InboxReportActionSurface = "toolbar",
) {
  const queryClient = useQueryClient();
  const clearSelection = useInboxReportSelectionStore(
    (state) => state.clearSelection,
  );
  const removeFromSelection = useInboxReportSelectionStore(
    (state) => state.removeFromSelection,
  );

  /**
   * Emit one `INBOX_REPORT_ACTION` per report the action succeeded for. Resolves
   * report metadata from the pre-mutation list (the query is invalidated right
   * after, dropping the affected reports), and skips firing when nothing landed.
   */
  const trackBulkAction = useCallback(
    (
      actionType: InboxBulkActionType,
      result: BulkActionResult,
      dismissal?: DismissReportDialogResult,
    ) => {
      if (result.successCount === 0) return;
      const byId = new Map(reports.map((report) => [report.id, report]));
      const succeeded = result.succeededIds
        .map((id) => byId.get(id))
        .filter((report): report is SignalReport => report !== undefined);
      if (succeeded.length === 0) return;
      const events = buildBulkActionEvents({
        reports: succeeded,
        actionType,
        surface,
        dismissal: dismissal
          ? { reason: dismissal.reason, note: dismissal.note }
          : undefined,
      });
      for (const event of events) {
        track(ANALYTICS_EVENTS.INBOX_REPORT_ACTION, event);
      }
    },
    [reports, surface],
  );

  /**
   * Reflect a bulk-action result in the selection: drop succeeded ids so the
   * user can retry the failed subset; keep everything if nothing succeeded so
   * the toast's "N failed" still points at a real selection.
   */
  const applyBulkResultToSelection = useCallback(
    (result: BulkActionResult) => {
      if (result.successCount === 0) return;
      if (result.failureCount === 0) {
        clearSelection();
        return;
      }
      removeFromSelection(result.succeededIds);
    },
    [clearSelection, removeFromSelection],
  );

  const effectiveBulkIds = effectiveBulkIdsFromSelection(selection);

  const eligibility = useMemo(
    () => getSelectedReportEligibility(reports, effectiveBulkIds),
    [reports, effectiveBulkIds],
  );

  const invalidateInboxQueries = useCallback(async () => {
    await queryClient.invalidateQueries({
      queryKey: reportKeys.all,
      exact: false,
    });
  }, [queryClient]);

  const suppressMutation = useAuthenticatedMutation(
    async (
      client,
      input: { reportIds: string[]; dismissal?: DismissReportDialogResult },
    ) => {
      // TODO: When dismissing a report that has an open implementation PR
      // (implementation_pr_url), close that PR on GitHub – likely in main, not here.
      return runBulkAction(input.reportIds, (reportId) =>
        client.updateSignalReportState(reportId, {
          state: "suppressed",
          ...(input.dismissal
            ? {
                dismissal_reason: input.dismissal.reason,
                dismissal_note: input.dismissal.note.slice(0, 4000),
              }
            : {}),
        }),
      );
    },
    {
      onSuccess: async (result, variables) => {
        trackBulkAction("dismiss", result, variables.dismissal);
        await invalidateInboxQueries();
        applyBulkResultToSelection(result);

        if (result.failureCount > 0) {
          toast.error(formatBulkActionSummary("suppress", result));
          return;
        }

        toast.success(formatBulkActionSummary("suppress", result));
      },
      onError: (error) => {
        toast.error(error.message || "Failed to archive reports");
      },
    },
  );

  const snoozeMutation = useAuthenticatedMutation(
    async (client, reportIds: string[]) =>
      runBulkAction(reportIds, (reportId) =>
        client.updateSignalReportState(reportId, {
          state: "potential",
          snooze_for: 1,
        }),
      ),
    {
      onSuccess: async (result) => {
        trackBulkAction("snooze", result);
        await invalidateInboxQueries();
        applyBulkResultToSelection(result);

        if (result.failureCount > 0) {
          toast.error(formatBulkActionSummary("snooze", result));
          return;
        }

        toast.success(formatBulkActionSummary("snooze", result));
      },
      onError: (error) => {
        toast.error(error.message || "Failed to snooze reports");
      },
    },
  );

  const deleteMutation = useAuthenticatedMutation(
    async (client, reportIds: string[]) =>
      runBulkAction(reportIds, (reportId) =>
        client.deleteSignalReport(reportId),
      ),
    {
      onSuccess: async (result) => {
        trackBulkAction("delete", result);
        await invalidateInboxQueries();
        applyBulkResultToSelection(result);

        if (result.failureCount > 0) {
          toast.error(formatBulkActionSummary("delete", result));
          return;
        }

        toast.success(formatBulkActionSummary("delete", result));
      },
      onError: (error) => {
        toast.error(error.message || "Failed to delete reports");
      },
    },
  );

  const reingestMutation = useAuthenticatedMutation(
    async (client, reportIds: string[]) =>
      runBulkAction(reportIds, (reportId) =>
        client.reingestSignalReport(reportId),
      ),
    {
      onSuccess: async (result) => {
        trackBulkAction("reingest", result);
        await invalidateInboxQueries();
        applyBulkResultToSelection(result);

        if (result.failureCount > 0) {
          toast.error(formatBulkActionSummary("reingest", result));
          return;
        }

        toast.success(formatBulkActionSummary("reingest", result));
      },
      onError: (error) => {
        toast.error(error.message || "Failed to reingest reports");
      },
    },
  );

  const suppressSelected = useCallback(
    async (dismissal?: DismissReportDialogResult) => {
      if (eligibility.suppressDisabledReason !== null) {
        return false;
      }

      await suppressMutation.mutateAsync({
        reportIds: eligibility.selectedIds,
        ...(dismissal != null ? { dismissal } : {}),
      });
      return true;
    },
    [
      eligibility.suppressDisabledReason,
      eligibility.selectedIds,
      suppressMutation,
    ],
  );

  const snoozeSelected = useCallback(async () => {
    if (eligibility.snoozeDisabledReason !== null) {
      return false;
    }

    await snoozeMutation.mutateAsync(eligibility.selectedIds);
    return true;
  }, [
    eligibility.snoozeDisabledReason,
    eligibility.selectedIds,
    snoozeMutation,
  ]);

  const deleteSelected = useCallback(async () => {
    if (eligibility.deleteDisabledReason !== null) {
      return false;
    }

    await deleteMutation.mutateAsync(eligibility.selectedIds);
    return true;
  }, [
    deleteMutation,
    eligibility.deleteDisabledReason,
    eligibility.selectedIds,
  ]);

  const reingestSelected = useCallback(async () => {
    if (eligibility.reingestDisabledReason !== null) {
      return false;
    }

    await reingestMutation.mutateAsync(eligibility.selectedIds);
    return true;
  }, [
    eligibility.reingestDisabledReason,
    eligibility.selectedIds,
    reingestMutation,
  ]);

  return {
    selectedReports: eligibility.selectedReports,
    selectedCount: eligibility.selectedCount,
    snoozeDisabledReason: eligibility.snoozeDisabledReason,
    suppressDisabledReason: eligibility.suppressDisabledReason,
    deleteDisabledReason: eligibility.deleteDisabledReason,
    reingestDisabledReason: eligibility.reingestDisabledReason,
    isSuppressing: suppressMutation.isPending,
    isSnoozing: snoozeMutation.isPending,
    isDeleting: deleteMutation.isPending,
    isReingesting: reingestMutation.isPending,
    suppressSelected,
    snoozeSelected,
    deleteSelected,
    reingestSelected,
  };
}
