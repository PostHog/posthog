import { ReceiptIcon } from "@phosphor-icons/react";
import type { SignalReport } from "@posthog/shared/types";
import { RefundReportDialog } from "@posthog/ui/features/inbox/components/RefundReportDialog";
import { useRefundReport } from "@posthog/ui/features/inbox/hooks/useRefundReport";
import { Button } from "@posthog/ui/primitives/Button";
import { useState } from "react";

/**
 * Refund control for a report's billed PR, shown in the detail action row.
 * Renders nothing unless the report is refund-eligible (flag on, billable PR,
 * not already refunded).
 */
export function ReportRefundAction({ report }: { report: SignalReport }) {
  const { canRefund, disabledReason, mutation } = useRefundReport(report);
  const [open, setOpen] = useState(false);

  if (!canRefund) {
    return null;
  }

  return (
    <>
      <Button
        type="button"
        variant="soft"
        color="gray"
        size="1"
        disabled={disabledReason !== null}
        disabledReason={disabledReason}
        onClick={() => setOpen(true)}
        tooltipContent="Refund this PR and archive the report"
      >
        <ReceiptIcon size={14} />
        Refund
      </Button>
      <RefundReportDialog
        open={open}
        onOpenChange={setOpen}
        report={report}
        isSubmitting={mutation.isPending}
        onConfirm={(input) =>
          mutation.mutate(input, { onSuccess: () => setOpen(false) })
        }
      />
    </>
  );
}
