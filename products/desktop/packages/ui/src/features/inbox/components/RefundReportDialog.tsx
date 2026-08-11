import {
  Button,
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Label,
  RadioGroup,
  RadioGroupItem,
  Textarea,
} from "@posthog/quill";
import { REFUND_REASON_OPTIONS } from "@posthog/shared";
import type {
  SignalReport,
  SignalReportRefundReason,
} from "@posthog/shared/types";
import { useId, useState } from "react";

export interface RefundReportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  report: SignalReport;
  isSubmitting: boolean;
  onConfirm: (result: {
    reason: SignalReportRefundReason;
    note: string;
  }) => void;
}

export function RefundReportDialog({
  open,
  onOpenChange,
  report,
  isSubmitting,
  onConfirm,
}: RefundReportDialogProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        // Don't let an Esc / backdrop dismiss abandon an in-flight refund.
        if (!next && isSubmitting) return;
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-md" showCloseButton={!isSubmitting}>
        <RefundReportDialogBody
          report={report}
          isSubmitting={isSubmitting}
          onConfirm={onConfirm}
        />
      </DialogContent>
    </Dialog>
  );
}

function RefundReportDialogBody({
  report,
  isSubmitting,
  onConfirm,
}: Omit<RefundReportDialogProps, "open" | "onOpenChange">) {
  const [reason, setReason] = useState<SignalReportRefundReason | null>(null);
  const [note, setNote] = useState("");
  const fieldId = useId();

  const title = report.title?.trim() ? report.title : "Untitled report";

  return (
    <>
      <DialogHeader>
        <DialogTitle>Refund the PR for "{title}"?</DialogTitle>
        <DialogDescription>
          You won't pay for this PR and it won't count toward your included PRs.
          The report is archived as part of the refund and can't be restored.
        </DialogDescription>
      </DialogHeader>

      <DialogBody>
        <div className="flex flex-col gap-4">
          <RadioGroup
            value={reason ?? ""}
            onValueChange={(value) =>
              setReason(value as SignalReportRefundReason)
            }
          >
            {REFUND_REASON_OPTIONS.map((option) => {
              const id = `${fieldId}-${option.value}`;
              return (
                <div key={option.value} className="flex items-center gap-2">
                  <RadioGroupItem value={option.value} id={id} />
                  <Label htmlFor={id} className="font-normal">
                    {option.label}
                  </Label>
                </div>
              );
            })}
          </RadioGroup>

          <Textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Optional: helps us review refunds"
            rows={3}
            maxLength={4000}
            disabled={isSubmitting}
          />
        </div>
      </DialogBody>

      <DialogFooter>
        <DialogClose
          render={
            <Button variant="outline" size="sm" disabled={isSubmitting} />
          }
        >
          Cancel
        </DialogClose>
        <Button
          variant="primary"
          size="sm"
          disabled={!reason || isSubmitting}
          loading={isSubmitting}
          onClick={() => reason && onConfirm({ reason, note: note.trim() })}
        >
          Refund
        </Button>
      </DialogFooter>
    </>
  );
}
