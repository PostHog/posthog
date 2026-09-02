import { EyeSlashIcon, PauseIcon } from "@phosphor-icons/react";
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
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import {
  DISMISSAL_REASON_OPTIONS,
  type DismissalReasonOptionValue,
  isDismissalReasonSnooze,
} from "@posthog/shared/dismissalReasons";
import type { SignalReport } from "@posthog/shared/types";
import { useId, useState } from "react";

export interface DismissReportDialogResult {
  reason: DismissalReasonOptionValue;
  note: string;
}

export interface DismissReportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  report: SignalReport;
  selectedCount?: number;
  isSubmitting: boolean;
  snoozeDisabledReason: string | null;
  initialReason?: DismissalReasonOptionValue;
  onConfirm: (result: DismissReportDialogResult) => void;
}

export function DismissReportDialog({
  open,
  onOpenChange,
  report,
  selectedCount = 1,
  isSubmitting,
  snoozeDisabledReason,
  initialReason,
  onConfirm,
}: DismissReportDialogProps): React.JSX.Element {
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && isSubmitting) return;
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-md" showCloseButton={!isSubmitting}>
        <DismissReportDialogBody
          report={report}
          selectedCount={selectedCount}
          isSubmitting={isSubmitting}
          snoozeDisabledReason={snoozeDisabledReason}
          initialReason={initialReason}
          onConfirm={onConfirm}
        />
      </DialogContent>
    </Dialog>
  );
}

function DismissReportDialogBody({
  report,
  selectedCount,
  isSubmitting,
  snoozeDisabledReason,
  initialReason,
  onConfirm,
}: Omit<DismissReportDialogProps, "open" | "onOpenChange"> & {
  selectedCount: number;
}): React.JSX.Element {
  const [reason, setReason] = useState<DismissalReasonOptionValue | null>(
    initialReason ?? null,
  );
  const [note, setNote] = useState("");
  const fieldId = useId();
  const pausesReport = reason != null && isDismissalReasonSnooze(reason);
  const reportNoun = selectedCount > 1 ? "reports" : "report";
  const title = report.title?.trim() ? report.title : "Untitled report";
  const hasOpenPr =
    Boolean(report.implementation_pr_url) &&
    report.implementation_pr_merged !== true;

  return (
    <>
      <DialogHeader>
        <DialogTitle>
          {pausesReport
            ? selectedCount > 1
              ? `Pause ${selectedCount} reports?`
              : `Pause report "${title}"?`
            : selectedCount > 1
              ? `Dismiss ${selectedCount} reports?`
              : `Dismiss report "${title}"?`}
        </DialogTitle>
        <DialogDescription>
          {pausesReport
            ? `This pauses the ${reportNoun} until another matching signal arrives.`
            : `This dismisses the ${reportNoun} for everyone in this project. Your feedback is saved and helps the agent.`}
          {hasOpenPr && !pausesReport
            ? " The open pull request will be closed."
            : ""}
        </DialogDescription>
      </DialogHeader>

      <DialogBody>
        <div className="flex flex-col gap-4">
          <RadioGroup
            value={reason ?? ""}
            onValueChange={(value) =>
              setReason(value as DismissalReasonOptionValue)
            }
          >
            {DISMISSAL_REASON_OPTIONS.map((option) => {
              const pauses = isDismissalReasonSnooze(option.value);
              const disabled = pauses && snoozeDisabledReason !== null;
              const id = `${fieldId}-${option.value}`;
              const explanation = disabled
                ? snoozeDisabledReason
                : pauses
                  ? "Pause this report until another matching signal arrives."
                  : "Dismiss this report so matching signals do not surface it again.";
              return (
                <div key={option.value} className="flex items-center gap-2">
                  <RadioGroupItem
                    value={option.value}
                    id={id}
                    disabled={disabled}
                  />
                  <Tooltip>
                    <TooltipTrigger
                      render={
                        <Label
                          htmlFor={id}
                          className="flex cursor-pointer items-center gap-1.5 font-normal"
                        />
                      }
                    >
                      {option.label}
                      {pauses ? (
                        <PauseIcon size={12} className="text-(--gray-9)" />
                      ) : (
                        <EyeSlashIcon size={12} className="text-(--gray-9)" />
                      )}
                    </TooltipTrigger>
                    <TooltipContent side="right">{explanation}</TooltipContent>
                  </Tooltip>
                </div>
              );
            })}
          </RadioGroup>

          <Textarea
            autoFocus={initialReason != null}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Optional: add detail"
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
          {pausesReport ? "Pause report" : "Dismiss report"}
        </Button>
      </DialogFooter>
    </>
  );
}
