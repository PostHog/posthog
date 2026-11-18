import { z } from "zod";

export const CANVAS_DRAG_TYPE = "application/x-posthog-canvas-id";
export const CANVAS_DRAG_DETAIL_TYPE = "application/x-posthog-canvas";

const canvasDragDetailSchema = z.object({
  id: z.string(),
  name: z.string().catch(""),
  channelId: z.string().nullable().catch(null),
});

export type CanvasDragDetail = z.infer<typeof canvasDragDetailSchema>;

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
  let parsed: unknown = null;
  try {
    parsed = JSON.parse(dataTransfer.getData(CANVAS_DRAG_DETAIL_TYPE) || "{}");
  } catch {
    parsed = null;
  }
  const detail = canvasDragDetailSchema.safeParse({
    id,
    ...(parsed as object),
  });
  return detail.success ? detail.data : { id, name: "", channelId: null };
}
