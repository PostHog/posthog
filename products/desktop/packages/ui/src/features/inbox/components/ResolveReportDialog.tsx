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
import {
  RESOLVE_REASON_OPTIONS,
  type ResolveReasonOptionValue,
} from "@posthog/shared/dismissalReasons";
import type { SignalReport } from "@posthog/shared/types";
import { useId, useState } from "react";

export interface ResolveReportDialogResult {
  reason: ResolveReasonOptionValue;
  note: string;
}

export function ResolveReportDialog({
  open,
  onOpenChange,
  report,
  isSubmitting,
  initialReason,
  initialNote = "",
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  report: SignalReport;
  isSubmitting: boolean;
  initialReason?: ResolveReasonOptionValue;
  initialNote?: string;
  onConfirm: (result: ResolveReportDialogResult) => void;
}): React.JSX.Element {
  const [reason, setReason] = useState<ResolveReasonOptionValue | null>(
    initialReason ?? null,
  );
  const [note, setNote] = useState(initialNote);
  const fieldId = useId();
  const title = report.title?.trim() ? report.title : "Untitled report";
  const hasOpenPr =
    Boolean(report.implementation_pr_url) &&
    report.implementation_pr_merged !== true;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && isSubmitting) return;
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-md" showCloseButton={!isSubmitting}>
        <DialogHeader>
          <DialogTitle>Resolve report "{title}"?</DialogTitle>
          <DialogDescription>
            This marks the report as done. If the issue returns, you get a new
            report linked to this one.
            {hasOpenPr ? " The open pull request will be closed." : ""}
          </DialogDescription>
        </DialogHeader>

        <DialogBody>
          <div className="flex flex-col gap-4">
            <RadioGroup
              value={reason ?? ""}
              onValueChange={(value) =>
                setReason(value as ResolveReasonOptionValue)
              }
            >
              {RESOLVE_REASON_OPTIONS.map((option) => {
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
              autoFocus={initialReason != null}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="Optional: link to the fix or explain what changed"
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
            onClick={() => reason && onConfirm({ reason, note })}
          >
            Resolve report
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
