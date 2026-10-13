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
  initialNote?: string;
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
  initialNote = "",
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
          initialNote={initialNote}
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
  initialNote = "",
  onConfirm,
}: Omit<DismissReportDialogProps, "open" | "onOpenChange"> & {
  selectedCount: number;
}): React.JSX.Element {
  const [reason, setReason] = useState<DismissalReasonOptionValue | null>(
    initialReason ?? null,
  );
  const [note, setNote] = useState(initialNote);
  const fieldId = useId();
  const pausesReport = reason != null && isDismissalReasonSnooze(reason);
  const reportNoun = selectedCount > 1 ? "reports" : "report";
  const title = report.title?.trim() ? report.title : "Untitled report";
  const hasOpenPr =
    Boolean(report.implementation_pr_url) &&
    report.implementation_pr_merged !== true;
  const pauseOptions = DISMISSAL_REASON_OPTIONS.filter((option) =>
    isDismissalReasonSnooze(option.value),
  );
  const hideOptions = DISMISSAL_REASON_OPTIONS.filter(
    (option) => !isDismissalReasonSnooze(option.value),
  );
  const outcome =
    reason == null
      ? null
      : pausesReport
        ? `The ${reportNoun} comes back if another matching signal arrives.`
        : `Matching signals won't surface the ${reportNoun} again.${hasOpenPr ? " The open pull request will be closed." : ""}`;

  const renderOption = (
    option: (typeof DISMISSAL_REASON_OPTIONS)[number],
    disabled: boolean,
  ): React.JSX.Element => {
    const id = `${fieldId}-${option.value}`;
    return (
      <div key={option.value} className="flex items-center gap-2">
        <RadioGroupItem value={option.value} id={id} disabled={disabled} />
        <Label htmlFor={id} className="cursor-pointer font-normal">
          {option.label}
        </Label>
      </div>
    );
  };

  return (
    <>
      <DialogHeader>
        <DialogTitle>
          {selectedCount > 1
            ? `Dismiss ${selectedCount} reports?`
            : `Dismiss report "${title}"?`}
        </DialogTitle>
        <DialogDescription>
          {`This dismisses the ${reportNoun} for everyone in this project. Your feedback is saved and helps the agent.`}
        </DialogDescription>
      </DialogHeader>

      <DialogBody>
        <div className="flex flex-col gap-4">
          <RadioGroup
            value={reason ?? ""}
            onValueChange={(value) =>
              setReason(value as DismissalReasonOptionValue)
            }
            className="gap-4"
          >
            <fieldset
              aria-describedby={
                snoozeDisabledReason ? `${fieldId}-pause-disabled` : undefined
              }
              className="flex flex-col gap-2"
            >
              <legend className="mb-2 font-medium text-(--gray-11) text-xs">
                Pause until a new matching signal
              </legend>
              {snoozeDisabledReason ? (
                <span
                  id={`${fieldId}-pause-disabled`}
                  className="-mt-2 text-(--gray-9) text-xs"
                >
                  {snoozeDisabledReason}
                </span>
              ) : null}
              {pauseOptions.map((option) =>
                renderOption(option, snoozeDisabledReason !== null),
              )}
            </fieldset>
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-2 font-medium text-(--gray-11) text-xs">
                Don't surface again
              </legend>
              {hideOptions.map((option) => renderOption(option, false))}
            </fieldset>
          </RadioGroup>

          <div className="flex flex-col gap-2">
            <Label
              htmlFor={`${fieldId}-note`}
              className="font-medium text-(--gray-11) text-xs"
            >
              Details (optional)
            </Label>
            <Textarea
              id={`${fieldId}-note`}
              autoFocus={initialReason != null}
              value={note}
              onChange={(event) => {
                const value = event.target.value;
                setNote(value);
                if (reason === null && value.trim()) {
                  setReason("other");
                }
              }}
              placeholder="What should the agent know?"
              rows={3}
              maxLength={4000}
              disabled={isSubmitting}
            />
          </div>

          <p
            aria-live="polite"
            className="text-muted-foreground text-xs empty:hidden"
          >
            {outcome}
          </p>
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
          Dismiss report
        </Button>
      </DialogFooter>
    </>
  );
}
