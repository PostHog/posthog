import {
  DISMISSAL_REASON_OPTIONS,
  type DismissalReasonOptionValue,
  isDismissalReasonSnooze,
} from "@posthog/shared/dismissalReasons";
import type { SignalReport } from "@posthog/shared/types";
import {
  ExplainedPauseLabel,
  ExplainedSuppressLabel,
} from "@posthog/ui/features/inbox/components/utils/ExplainedDismissOptionLabels";
import { Button } from "@posthog/ui/primitives/Button";
import { Dialog, Flex, RadioGroup, Text, TextArea } from "@radix-ui/themes";
import { useEffect, useRef, useState } from "react";

export interface DismissReportDialogResult {
  reason: DismissalReasonOptionValue;
  note: string;
}

export interface DismissReportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  report: SignalReport;
  /** When greater than 1, copy reflects a bulk dismiss of the current selection. */
  selectedCount?: number;
  isSubmitting: boolean;
  /**
   * When snooze is not allowed for the current selection, the "Already fixed"
   * option is disabled because that path snoozes instead of dismissing.
   */
  snoozeDisabledReason: string | null;
  onConfirm: (result: DismissReportDialogResult) => void;
}

export function DismissReportDialog({
  open,
  onOpenChange,
  report,
  selectedCount = 1,
  isSubmitting,
  snoozeDisabledReason,
  onConfirm,
}: DismissReportDialogProps) {
  const onOpenChangeRef = useRef(onOpenChange);
  onOpenChangeRef.current = onOpenChange;

  // Radix Themes nests Content inside the overlay scroll area, so backdrop clicks
  // often land on padding/overlay nodes that never reach Content's dismiss layer.
  useEffect(() => {
    if (!open || isSubmitting) return;

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;

      const overlay = document.querySelector(
        '.rt-DialogOverlay[data-state="open"]',
      );
      const content = document.querySelector(
        '.rt-DialogContent[data-state="open"]',
      );
      if (!overlay?.contains(target) || content?.contains(target)) return;

      onOpenChangeRef.current(false);
    };

    document.addEventListener("pointerdown", handlePointerDown, true);
    return () =>
      document.removeEventListener("pointerdown", handlePointerDown, true);
  }, [open, isSubmitting]);

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Content
        maxWidth="480px"
        onPointerDownOutside={() => {
          if (!isSubmitting) onOpenChange(false);
        }}
        onEscapeKeyDown={() => {
          if (!isSubmitting) onOpenChange(false);
        }}
      >
        <DismissReportDialogBody
          report={report}
          selectedCount={selectedCount}
          isSubmitting={isSubmitting}
          snoozeDisabledReason={snoozeDisabledReason}
          onConfirm={onConfirm}
        />
      </Dialog.Content>
    </Dialog.Root>
  );
}

function DismissReportDialogBody({
  report,
  selectedCount,
  isSubmitting,
  snoozeDisabledReason,
  onConfirm,
}: Omit<DismissReportDialogProps, "open" | "onOpenChange"> & {
  selectedCount: number;
}) {
  const [reason, setReason] = useState<DismissalReasonOptionValue | null>(null);
  const [note, setNote] = useState("");

  const handleConfirm = () => {
    if (!reason) return;
    onConfirm({ reason, note: note.trim() });
  };

  const alreadyFixedDisabled = snoozeDisabledReason !== null;
  const pausesReport = reason != null && isDismissalReasonSnooze(reason);
  const reportNoun = selectedCount > 1 ? "reports" : "report";

  return (
    <>
      <Dialog.Title>
        <Text className="text-balance font-bold text-lg">
          {pausesReport
            ? selectedCount > 1
              ? `Pause ${selectedCount} reports?`
              : `Pause report "${report.title?.trim() ? report.title : "Untitled report"}"?`
            : selectedCount > 1
              ? `Archive ${selectedCount} reports for everyone?`
              : `Archive report "${report.title?.trim() ? report.title : "Untitled report"}" for everyone?`}
        </Text>
      </Dialog.Title>
      <Dialog.Description className="text-gray-10 text-sm">
        {pausesReport
          ? `This pauses the ${reportNoun} for everyone in this project until another matching signal arrives. The ${reportNoun} can then return.`
          : `This archives the ${reportNoun} for everyone in this project. Your feedback is saved and helps the agent.`}
      </Dialog.Description>

      <Flex direction="column" gap="4" mt="4">
        <RadioGroup.Root
          size="1"
          value={reason ?? ""}
          onValueChange={(value) =>
            setReason(value as DismissalReasonOptionValue)
          }
        >
          <Flex direction="column" gap="2">
            {DISMISSAL_REASON_OPTIONS.map((option) => {
              const snoozesInsteadOfDismiss = isDismissalReasonSnooze(
                option.value,
              );
              const disabled = snoozesInsteadOfDismiss && alreadyFixedDisabled;

              return snoozesInsteadOfDismiss ? (
                <ExplainedPauseLabel
                  key={option.value}
                  label={option.label}
                  value={option.value}
                  disabled={disabled}
                  disabledReason={disabled ? snoozeDisabledReason : undefined}
                />
              ) : (
                <ExplainedSuppressLabel
                  key={option.value}
                  label={option.label}
                  value={option.value}
                />
              );
            })}
          </Flex>
        </RadioGroup.Root>

        <TextArea
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Optional: add detail"
          size="1"
          rows={3}
          maxLength={4000}
          disabled={isSubmitting}
        />
      </Flex>

      <Flex gap="3" mt="4" justify="end">
        <Dialog.Close>
          <Button variant="soft" color="gray">
            Cancel
          </Button>
        </Dialog.Close>
        <Button
          variant="solid"
          disabled={!reason || isSubmitting}
          disabledReason={!reason ? "you haven't picked a reason" : null}
          onClick={handleConfirm}
          loading={isSubmitting}
        >
          {pausesReport ? "Pause for everyone" : "Archive for everyone"}
        </Button>
      </Flex>
    </>
  );
}
