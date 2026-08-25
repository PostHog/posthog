import { ArchiveIcon } from "@phosphor-icons/react";
import {
  Button,
  Spinner,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { isDismissalReasonSnooze } from "@posthog/shared/dismissalReasons";
import type { SignalReport } from "@posthog/shared/types";
import {
  DismissReportDialog,
  type DismissReportDialogResult,
} from "@posthog/ui/features/inbox/components/DismissReportDialog";
import { useInboxBulkActions } from "@posthog/ui/features/inbox/hooks/useInboxBulkActions";
import { type ReactElement, useCallback, useMemo, useState } from "react";

const EMPTY_REPORTS: SignalReport[] = [];

/** Archive flow used by every inbox detail screen – one report, one button + dialog. */
export function useInboxReportDismissAction(report: SignalReport): {
  actionButton: ReactElement;
  dialog: ReactElement | null;
  /** Open the archive dialog directly — for menu items and keyboard paths. */
  openDialog: () => void;
} {
  const [open, setOpen] = useState(false);
  // Stable identity for the closed case so `useInboxBulkActions`'s memo doesn't
  // bust on every parent render. When the dialog is closed we also pass
  // `null` selection so the bulk hook short-circuits to its `emptyBulkIds`.
  const reportsForActions = useMemo(
    () => (open ? [report] : EMPTY_REPORTS),
    [open, report],
  );
  const bulkActions = useInboxBulkActions(
    reportsForActions,
    open ? report.id : null,
    "detail_pane",
  );

  const isPending = bulkActions.isSuppressing || bulkActions.isSnoozing;

  const handleConfirm = useCallback(
    async (result: DismissReportDialogResult) => {
      const isSnooze = isDismissalReasonSnooze(result.reason);
      const ok = isSnooze
        ? await bulkActions.snoozeSelected()
        : await bulkActions.suppressSelected(result);
      if (ok) setOpen(false);
    },
    [bulkActions],
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
            aria-label="Archive this report"
            disabled={isPending}
            onClick={() => setOpen(true)}
          />
        }
      >
        {isPending ? <Spinner /> : <ArchiveIcon size={12} />}
      </TooltipTrigger>
      <TooltipContent>Archive</TooltipContent>
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
      onConfirm={handleConfirm}
    />
  ) : null;

  const openDialog = useCallback(() => setOpen(true), []);
  return { actionButton, dialog, openDialog };
}
