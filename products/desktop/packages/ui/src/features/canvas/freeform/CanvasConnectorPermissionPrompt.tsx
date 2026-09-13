import type { CanvasConnectorPermission } from "@posthog/core/canvas/canvasConnectorPermissionService";
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
import { useRef } from "react";

export function CanvasConnectorPermissionPrompt({
  request,
  onRespond,
}: {
  request: CanvasConnectorPermission | undefined;
  onRespond: (allowed: boolean) => void;
}) {
  const denyButtonRef = useRef<HTMLButtonElement>(null);
  return (
    <Dialog
      open={!!request}
      onOpenChange={(open) => {
        if (!open) onRespond(false);
      }}
    >
      <DialogContent
        className="max-w-lg"
        showCloseButton={false}
        initialFocus={denyButtonRef}
      >
        <DialogHeader>
          <DialogTitle>
            {request?.reason === "tool"
              ? "Allow this tool call?"
              : "Allow this canvas to use your connection?"}
          </DialogTitle>
          <DialogDescription>
            {request?.reason === "tool"
              ? "This tool is set to ask for permission. Allow only this call. Your saved tool permissions will not change."
              : "This canvas wants to read data with your connection. Only allow canvases you trust."}
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 rounded border p-3 text-sm">
            <dt>Connection</dt>
            <dd className="break-all">{request?.provider}</dd>
            <dt>Tool</dt>
            <dd className="break-all font-mono">{request?.tool}</dd>
          </dl>
          {request?.reason === "tool" && (
            <details className="mt-3 text-sm">
              <summary>Call arguments</summary>
              <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-all rounded border p-3">
                {JSON.stringify(request.arguments ?? {}, null, 2)}
              </pre>
            </details>
          )}
          <p className="mt-3 text-sm">
            The canvas can receive private data and share it through its
            declared capabilities.
          </p>
        </DialogBody>
        <DialogFooter>
          <Button
            ref={denyButtonRef}
            variant="outline"
            onClick={() => onRespond(false)}
          >
            Deny
          </Button>
          <Button variant="primary" onClick={() => onRespond(true)}>
            {request?.reason === "tool" ? "Allow once" : "Allow access"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
