import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@posthog/quill";

interface CanvasAgentRequestDialogProps {
  prompt: string | null;
  loading: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export function CanvasAgentRequestDialog({
  prompt,
  loading,
  onCancel,
  onConfirm,
}: CanvasAgentRequestDialogProps) {
  return (
    <Dialog
      open={prompt !== null}
      onOpenChange={(open) => {
        if (!open && !loading) onCancel();
      }}
    >
      <DialogContent className="max-w-lg" showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>Ask the canvas agent to make this change?</DialogTitle>
          <DialogDescription>
            Review the exact request. Accepting starts an agent run that uses
            compute. The result arrives as a draft for review.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded border bg-surface-primary p-3 text-sm">
            {prompt}
          </pre>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" disabled={loading} onClick={onCancel}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={loading}
            data-attr="canvas-agent-request-confirm"
            onClick={onConfirm}
          >
            Accept and run
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
