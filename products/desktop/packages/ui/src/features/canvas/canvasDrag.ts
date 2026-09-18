export const CANVAS_DRAG_TYPE = "application/x-posthog-canvas-id";
export const CANVAS_DRAG_DETAIL_TYPE = "application/x-posthog-canvas";

export interface CanvasDragDetail {
  id: string;
  name: string;
  channelId: string | null;
}

export function writeCanvasDragData(
  dataTransfer: Pick<DataTransfer, "setData">,
  canvasId: string,
  detail?: Omit<CanvasDragDetail, "id">,
): void {
  dataTransfer.setData(CANVAS_DRAG_TYPE, canvasId);
  if (detail) {
    const payload: CanvasDragDetail = { id: canvasId, ...detail };
    dataTransfer.setData(CANVAS_DRAG_DETAIL_TYPE, JSON.stringify(payload));
  }
}

export function readCanvasDragData(
  dataTransfer: Pick<DataTransfer, "getData">,
): string | null {
  return dataTransfer.getData(CANVAS_DRAG_TYPE) || null;
}

export function readCanvasDragDetail(
  dataTransfer: Pick<DataTransfer, "getData">,
): CanvasDragDetail | null {
  const id = readCanvasDragData(dataTransfer);
  if (!id) return null;
  const serialized = dataTransfer.getData(CANVAS_DRAG_DETAIL_TYPE);
  if (!serialized) return { id, name: "", channelId: null };
  try {
    const parsed = JSON.parse(serialized) as Partial<CanvasDragDetail>;
    return {
      id,
      name: typeof parsed.name === "string" ? parsed.name : "",
      channelId: typeof parsed.channelId === "string" ? parsed.channelId : null,
    };
  } catch {
    return { id, name: "", channelId: null };
  }
}
