import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
} from "@posthog/quill";
import type { ReactElement } from "react";

interface DisconnectIntegrationDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  isPending: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function DisconnectIntegrationDialog({
  open,
  title,
  description,
  confirmLabel = "Disconnect",
  isPending,
  onConfirm,
  onCancel,
}: DisconnectIntegrationDialogProps): ReactElement {
  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !isPending) onCancel();
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={isPending}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={onConfirm}
            loading={isPending}
            disabled={isPending}
          >
            {confirmLabel}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
