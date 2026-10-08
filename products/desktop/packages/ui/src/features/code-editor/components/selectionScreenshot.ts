import type { IScreenCapture } from "@posthog/platform/screen-capture";
import { screenshotArea } from "@posthog/shared/screenshot-area";

const ACCENT = "#f54e00";
const PIN_SIZE = 22;

export type CaptureBounds = {
  top: number;
  left: number;
  right: number;
  bottom: number;
};

export type SelectionAnchor = {
  top: number;
  endX: number;
  bottom: number;
  startX?: number;
  startTop?: number;
  bounds?: CaptureBounds;
};

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("Screenshot did not load"));
    image.src = src;
  });
}

function drawPin(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  size: number,
): void {
  const radius = size / 2;
  context.save();
  context.translate(x, y);
  context.rotate(-Math.PI / 4);
  context.beginPath();
  context.moveTo(-radius, 0);
  context.arc(0, 0, radius, Math.PI, Math.PI / 2, false);
  context.lineTo(-radius, radius);
  context.closePath();
  context.fillStyle = ACCENT;
  context.shadowColor = "rgba(0,0,0,0.35)";
  context.shadowBlur = size / 4;
  context.fill();
  context.shadowBlur = 0;
  context.lineWidth = size / 11;
  context.strokeStyle = "#ffffff";
  context.stroke();
  context.restore();
}

export async function pinScreenshot(
  dataUrl: string,
  pin: { x: number; y: number },
  areaWidth: number,
): Promise<string> {
  const image = await loadImage(dataUrl);
  const canvas = document.createElement("canvas");
  canvas.width = image.naturalWidth;
  canvas.height = image.naturalHeight;
  const context = canvas.getContext("2d");
  if (!context) return dataUrl;
  context.drawImage(image, 0, 0);
  const scale = image.naturalWidth / areaWidth;
  drawPin(context, pin.x * scale, pin.y * scale, PIN_SIZE * scale);
  return canvas.toDataURL("image/png");
}

export async function captureSelectionScreenshot(
  capture: IScreenCapture,
  anchor: SelectionAnchor,
): Promise<string | null> {
  const bounds = {
    left: Math.max(0, anchor.bounds?.left ?? 0),
    top: Math.max(0, anchor.bounds?.top ?? 0),
    right: Math.min(
      window.innerWidth,
      anchor.bounds?.right ?? window.innerWidth,
    ),
    bottom: Math.min(
      window.innerHeight,
      anchor.bounds?.bottom ?? window.innerHeight,
    ),
  };
  const local = screenshotArea(
    {
      top: Math.min(anchor.startTop ?? anchor.top, anchor.top) - bounds.top,
      bottom: anchor.bottom - bounds.top,
      left: Math.min(anchor.startX ?? anchor.endX, anchor.endX) - bounds.left,
      right: Math.max(anchor.startX ?? anchor.endX, anchor.endX) - bounds.left,
    },
    { width: bounds.right - bounds.left, height: bounds.bottom - bounds.top },
  );
  if (!local) return null;
  const area = { ...local, x: local.x + bounds.left, y: local.y + bounds.top };
  try {
    const dataUrl = await capture.captureRegion(area);
    if (!dataUrl) return null;
    return await pinScreenshot(
      dataUrl,
      { x: anchor.endX - area.x, y: anchor.top - area.y },
      area.width,
    );
  } catch {
    return null;
  }
}
