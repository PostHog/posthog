import { ArrowCounterClockwiseIcon } from "@phosphor-icons/react";
import { isRestorableReport } from "@posthog/core/inbox/reportMembership";
import { Button } from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { useInboxRestoreReport } from "@posthog/ui/features/inbox/hooks/useInboxRestoreReport";
import { Spinner, Tooltip } from "@radix-ui/themes";

/**
 * Restore for an archived report row — the Archive tab's action, now living on
 * the rows the Archived bucket lists. Only suppressed reports restore; resolved
 * ones (their PR merged) are terminal and render no action.
 */
export function ReportRestoreButton({ report }: { report: SignalReport }) {
  const restore = useInboxRestoreReport();
  if (!isRestorableReport(report)) return null;
  const isPending = restore.isPending && restore.variables === report.id;
  return (
    <Tooltip content="Restore this report">
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-label="Restore this report"
        disabled={isPending}
        onClick={(event) => {
          event.stopPropagation();
          restore.mutate(report.id);
        }}
      >
        {isPending ? (
          <Spinner size="1" />
        ) : (
          <ArrowCounterClockwiseIcon size={12} />
        )}
      </Button>
    </Tooltip>
  );
}
