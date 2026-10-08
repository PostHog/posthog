export const CANVAS_EDITOR_CHANNEL = "posthog-canvas";

export function canvasEditorFrame(): HTMLIFrameElement | null {
  return document.querySelector<HTMLIFrameElement>(
    "iframe[data-canvas-source-editor]",
  );
}

export function postToCanvasEditor(message: Record<string, unknown>): void {
  canvasEditorFrame()?.contentWindow?.postMessage(
    { channel: CANVAS_EDITOR_CHANNEL, ...message },
    "*",
  );
}
