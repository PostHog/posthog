import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FieldError,
} from "@posthog/quill";

export function SpaceSetupRetryDialog({
  open,
  onOpenChange,
  error,
  busy,
  onRetry,
  onOpenSpace,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  error: string;
  busy: boolean;
  onRetry: () => void;
  onOpenSpace: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent showCloseButton={false} className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Setup did not start</DialogTitle>
          <DialogDescription>
            Your space was created. Retry setup to use the details you entered,
            or open the space without setup.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <FieldError className="break-words">{error}</FieldError>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={onOpenSpace}>
            Open space
          </Button>
          <Button
            variant="primary"
            disabled={busy}
            loading={busy}
            onClick={onRetry}
          >
            Retry setup
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
