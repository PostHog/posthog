import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  DialogBody,
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
    <AlertDialog open={prompt !== null} onOpenChange={() => undefined}>
      <AlertDialogContent className="max-w-lg">
        <AlertDialogHeader>
          <AlertDialogTitle>
            Ask the canvas agent to make this change?
          </AlertDialogTitle>
          <AlertDialogDescription>
            Review the exact request. Accepting starts an agent run that uses
            compute. The result arrives as a draft for review.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <DialogBody>
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded border bg-surface-primary p-3 text-sm">
            {prompt}
          </pre>
        </DialogBody>
        <AlertDialogFooter>
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
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
