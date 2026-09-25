import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
} from "@posthog/quill";
import type { SignalReportCheck } from "@posthog/shared/types";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { useState } from "react";

/**
 * Stopping a check is terminal: it will not run, and its author has to write a new one to get
 * the answer back. So the action confirms, and says what survives.
 */
export function StopReportCheckDialog({
  check,
  onConfirm,
  onCancel,
}: {
  check: SignalReportCheck | null;
  onConfirm: (checkId: string) => Promise<void>;
  onCancel: () => void;
}) {
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleConfirm = async () => {
    if (isSubmitting || !check) return;
    setIsSubmitting(true);
    try {
      await onConfirm(check.id);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AlertDialog
      open={check !== null}
      onOpenChange={(isOpen) => {
        if (!isOpen && !isSubmitting) onCancel();
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Stop this check?</AlertDialogTitle>
          <AlertDialogDescription>
            {check?.title ? `"${check.title}"` : "This check"} will not run, and
            nothing will report back on it. Results it already recorded stay on
            this report.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <Button variant="outline" disabled={isSubmitting} onClick={onCancel}>
            Keep it
          </Button>
          <Button
            variant="destructive"
            disabled={isSubmitting}
            onClick={handleConfirm}
          >
            {isSubmitting && <Spinner aria-hidden="true" />}
            Stop check
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
