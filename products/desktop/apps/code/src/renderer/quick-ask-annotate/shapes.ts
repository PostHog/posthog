export interface Point {
  x: number;
  y: number;
}

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export type Tool = "arrow" | "rect" | "ellipse" | "pen" | "text" | "pixelate";

export type Shape =
  | { kind: "rect"; rect: Rect; color: string }
  | { kind: "ellipse"; rect: Rect; color: string }
  | { kind: "arrow"; from: Point; to: Point; color: string }
  | { kind: "pen"; points: Point[]; color: string }
  | { kind: "text"; at: Point; text: string; color: string }
  | { kind: "pixelate"; rect: Rect };

export const LINE_WIDTH = 3;
export const TEXT_SIZE = 17;
export const TEXT_FONT = `600 ${TEXT_SIZE}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`;
/** View pixels per pixelation block. */
const PIXEL_BLOCK = 12;

export function normalizeRect(a: Point, b: Point): Rect {
  return {
    x: Math.min(a.x, b.x),
    y: Math.min(a.y, b.y),
    w: Math.abs(a.x - b.x),
    h: Math.abs(a.y - b.y),
  };
}

/** How shapes sample the underlying shot (for pixelate). */
export interface DrawEnv {
  image: HTMLImageElement;
  /** Shot pixels per view pixel, per axis. */
  sx: number;
  sy: number;
}

export function drawShape(
  ctx: CanvasRenderingContext2D,
  shape: Shape,
  env: DrawEnv,
): void {
  ctx.lineWidth = LINE_WIDTH;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  switch (shape.kind) {
    case "rect": {
      const { x, y, w, h } = shape.rect;
      ctx.strokeStyle = shape.color;
      ctx.beginPath();
      ctx.roundRect(x, y, w, h, 4);
      ctx.stroke();
      return;
    }
    case "ellipse": {
      const { x, y, w, h } = shape.rect;
      ctx.strokeStyle = shape.color;
      ctx.beginPath();
      ctx.ellipse(x + w / 2, y + h / 2, w / 2, h / 2, 0, 0, Math.PI * 2);
      ctx.stroke();
      return;
    }
    case "arrow": {
      const { from, to } = shape;
      const angle = Math.atan2(to.y - from.y, to.x - from.x);
      const length = Math.hypot(to.x - from.x, to.y - from.y);
      const head = Math.min(Math.max(11, length * 0.22), 26);
      ctx.strokeStyle = shape.color;
      ctx.fillStyle = shape.color;
      ctx.beginPath();
      ctx.moveTo(from.x, from.y);
      // Stop the shaft short of the tip so it never pokes past the head.
      ctx.lineTo(
        to.x - head * 0.6 * Math.cos(angle),
        to.y - head * 0.6 * Math.sin(angle),
      );
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(to.x, to.y);
      ctx.lineTo(
        to.x - head * Math.cos(angle - Math.PI / 7),
        to.y - head * Math.sin(angle - Math.PI / 7),
      );
      ctx.lineTo(
        to.x - head * Math.cos(angle + Math.PI / 7),
        to.y - head * Math.sin(angle + Math.PI / 7),
      );
      ctx.closePath();
      ctx.fill();
      return;
    }
    case "pen": {
      if (shape.points.length < 2) return;
      ctx.strokeStyle = shape.color;
      ctx.beginPath();
      ctx.moveTo(shape.points[0].x, shape.points[0].y);
      for (const point of shape.points.slice(1)) {
        ctx.lineTo(point.x, point.y);
      }
      ctx.stroke();
      return;
    }
    case "text": {
      ctx.font = TEXT_FONT;
      ctx.textBaseline = "top";
      ctx.fillStyle = shape.color;
      let y = shape.at.y;
      for (const line of shape.text.split("\n")) {
        ctx.fillText(line, shape.at.x, y);
        y += TEXT_SIZE * 1.25;
      }
      return;
    }
    case "pixelate": {
      const { x, y, w, h } = shape.rect;
      if (w < 2 || h < 2) return;
      const blocksW = Math.max(1, Math.round(w / PIXEL_BLOCK));
      const blocksH = Math.max(1, Math.round(h / PIXEL_BLOCK));
      const small = document.createElement("canvas");
      small.width = blocksW;
      small.height = blocksH;
      const smallCtx = small.getContext("2d");
      if (!smallCtx) return;
      smallCtx.drawImage(
        env.image,
        x * env.sx,
        y * env.sy,
        w * env.sx,
        h * env.sy,
        0,
        0,
        blocksW,
        blocksH,
      );
      const smoothing = ctx.imageSmoothingEnabled;
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(small, 0, 0, blocksW, blocksH, x, y, w, h);
      ctx.imageSmoothingEnabled = smoothing;
      return;
    }
  }
}
