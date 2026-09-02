import { ArchiveIcon } from "@phosphor-icons/react";
import {
  Button,
  Spinner,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type { InboxReportActionSurface } from "@posthog/shared/analytics-events";
import {
  type DismissalReasonOptionValue,
  isDismissalReasonSnooze,
} from "@posthog/shared/dismissalReasons";
import type { SignalReport } from "@posthog/shared/types";
import {
  DismissReportDialog,
  type DismissReportDialogResult,
} from "@posthog/ui/features/inbox/components/DismissReportDialog";
import { useInboxBulkActions } from "@posthog/ui/features/inbox/hooks/useInboxBulkActions";
import { type ReactElement, useCallback, useMemo, useState } from "react";

/** Dismiss flow used by every inbox detail screen – one report, one button + dialog. */
export function useInboxReportDismissAction(
  report: SignalReport,
  surface: InboxReportActionSurface = "detail_pane",
  triageId?: string,
): {
  actionButton: ReactElement;
  dialog: ReactElement | null;
  openDialog: (initialReason?: DismissalReasonOptionValue) => void;
  dismissWithReason: (
    reason: DismissalReasonOptionValue,
    note?: string,
  ) => Promise<void>;
} {
  const [open, setOpen] = useState(false);
  const [initialReason, setInitialReason] =
    useState<DismissalReasonOptionValue>();
  const reportsForActions = useMemo(() => [report], [report]);
  const bulkActions = useInboxBulkActions(
    reportsForActions,
    report.id,
    surface,
    triageId,
  );

  const isPending = bulkActions.isSuppressing || bulkActions.isSnoozing;

  const dismissWithReason = useCallback(
    async (reason: DismissalReasonOptionValue, note = "") => {
      const result = { reason, note } satisfies DismissReportDialogResult;
      const isSnooze = isDismissalReasonSnooze(reason);
      setOpen(false);
      const ok = isSnooze
        ? await bulkActions.snoozeSelected(result)
        : await bulkActions.suppressSelected(result);
      if (!ok) setOpen(true);
    },
    [bulkActions],
  );
  const handleConfirm = useCallback(
    (result: DismissReportDialogResult) =>
      dismissWithReason(result.reason, result.note),
    [dismissWithReason],
  );

  const actionButton = (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            type="button"
            variant="outline"
            size="icon-xs"
            className="h-7 w-7"
            aria-label="Dismiss this report for everyone in the project"
            disabled={isPending}
            onClick={() => setOpen(true)}
          />
        }
      >
        {isPending ? <Spinner /> : <ArchiveIcon size={12} />}
      </TooltipTrigger>
      <TooltipContent>Dismiss for everyone in this project</TooltipContent>
    </Tooltip>
  );

  const dialog = open ? (
    <DismissReportDialog
      open={open}
      onOpenChange={(next) => {
        if (!isPending) setOpen(next);
      }}
      report={report}
      isSubmitting={isPending}
      snoozeDisabledReason={bulkActions.snoozeDisabledReason}
      initialReason={initialReason}
      onConfirm={handleConfirm}
    />
  ) : null;

  const openDialog = useCallback((reason?: DismissalReasonOptionValue) => {
    setInitialReason(reason);
    setOpen(true);
  }, []);
  return { actionButton, dialog, openDialog, dismissWithReason };
}
