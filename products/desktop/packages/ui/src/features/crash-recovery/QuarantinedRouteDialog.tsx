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

interface QuarantinedRouteDialogProps {
  open: boolean;
  /** Set when the quarantined route was a task, which is the archivable case. */
  canArchive: boolean;
  isArchiving: boolean;
  onOpenAnyway: () => void;
  onArchive: () => void;
  onDismiss: () => void;
}

/**
 * Says why the app did not open where it was left. Without this the recovery
 * reads as the app losing the user's place for no reason.
 */
export function QuarantinedRouteDialog({
  open,
  canArchive,
  isArchiving,
  onOpenAnyway,
  onArchive,
  onDismiss,
}: QuarantinedRouteDialogProps): ReactElement {
  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !isArchiving) onDismiss();
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {canArchive
              ? "This task closed the app"
              : "This screen closed the app"}
          </AlertDialogTitle>
          <AlertDialogDescription>
            PostHog closed twice while it was open, so this time it started
            somewhere else. A very long agent response can use more memory than
            the app has.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <Button variant="outline" disabled={isArchiving} onClick={onDismiss}>
            Close
          </Button>
          <Button
            variant="outline"
            disabled={isArchiving}
            onClick={onOpenAnyway}
          >
            Open anyway
          </Button>
          {canArchive ? (
            <Button
              variant="primary"
              loading={isArchiving}
              disabled={isArchiving}
              onClick={onArchive}
            >
              Archive task
            </Button>
          ) : null}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
