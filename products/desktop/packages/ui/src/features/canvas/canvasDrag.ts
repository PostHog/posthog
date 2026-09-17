export const CANVAS_DRAG_TYPE = "application/x-posthog-canvas-id";

export function writeCanvasDragData(
  dataTransfer: Pick<DataTransfer, "setData">,
  canvasId: string,
): void {
  dataTransfer.setData(CANVAS_DRAG_TYPE, canvasId);
}

export function readCanvasDragData(
  dataTransfer: Pick<DataTransfer, "getData">,
): string | null {
  return dataTransfer.getData(CANVAS_DRAG_TYPE) || null;
}
