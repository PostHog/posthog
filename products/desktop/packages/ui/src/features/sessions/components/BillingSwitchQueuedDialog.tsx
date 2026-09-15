import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
} from "@posthog/quill";
import { type ReactElement, useRef } from "react";

interface BillingSwitchQueuedDialogProps {
  open: boolean;
  queuedCount: number;
  onConfirm: () => void;
  onCancel: () => void;
}

export function BillingSwitchQueuedDialog({
  open,
  ...props
}: BillingSwitchQueuedDialogProps): ReactElement | null {
  if (!open) return null;
  return <OpenBillingSwitchQueuedDialog open {...props} />;
}

function OpenBillingSwitchQueuedDialog({
  open,
  queuedCount,
  onConfirm,
  onCancel,
}: BillingSwitchQueuedDialogProps): ReactElement {
  const cancelButtonRef = useRef<HTMLButtonElement>(null);
  const messages =
    queuedCount === 1 ? "1 queued message" : `${queuedCount} queued messages`;

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onCancel();
      }}
    >
      <AlertDialogContent initialFocus={cancelButtonRef}>
        <AlertDialogHeader>
          <AlertDialogTitle>Switch billing?</AlertDialogTitle>
          <AlertDialogDescription>
            Switching billing restarts the agent on your next message and
            resends the conversation. Your {messages} will be discarded.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter className="flex-row justify-end">
          <Button ref={cancelButtonRef} variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            variant="primary"
            data-attr="billing-switch-queued-dialog-confirm"
            onClick={onConfirm}
          >
            Switch billing
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
