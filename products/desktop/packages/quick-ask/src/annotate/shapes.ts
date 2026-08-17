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

export type Tool =
  | "select"
  | "crop"
  | "arrow"
  | "rect"
  | "ellipse"
  | "pen"
  | "text"
  | "counter"
  | "pixelate";

export type Shape =
  | { kind: "rect"; rect: Rect; color: string }
  | { kind: "ellipse"; rect: Rect; color: string }
  | { kind: "arrow"; from: Point; to: Point; color: string }
  | { kind: "pen"; points: Point[]; color: string }
  | {
      kind: "text";
      at: Point;
      text: string;
      color: string;
      bg: boolean;
      size: number;
      /** Wrap width in view pixels; unset text stays on its typed lines. */
      width?: number;
    }
  | { kind: "counter"; at: Point; n: number; color: string }
  | { kind: "pixelate"; rect: Rect };

export const LINE_WIDTH = 3;
export const TEXT_SIZE = 17;
export const TEXT_MIN_SIZE = 12;
export const TEXT_MAX_SIZE = 48;
export const TEXT_MIN_WIDTH = 48;
export const TEXT_LINE = 1.25;
export const COUNTER_RADIUS = 14;
export const TEXT_BG_PAD_X = 8;
export const TEXT_BG_PAD_Y = 5;

export function textFont(size: number): string {
  return `600 ${size}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`;
}
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

/** Ink readable on top of the given ink color: dark on light, white on dark. */
export function contrastInk(color: string): string {
  const hex = color.replace("#", "");
  if (hex.length !== 6) return "#ffffff";
  const r = Number.parseInt(hex.slice(0, 2), 16);
  const g = Number.parseInt(hex.slice(2, 4), 16);
  const b = Number.parseInt(hex.slice(4, 6), 16);
  return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? "#1c1d22" : "#ffffff";
}

let measureCtx: CanvasRenderingContext2D | null = null;

function measurer(size: number): CanvasRenderingContext2D | null {
  if (!measureCtx) {
    measureCtx = document.createElement("canvas").getContext("2d");
  }
  if (measureCtx) measureCtx.font = textFont(size);
  return measureCtx;
}

/** Typed lines, word-wrapped to the shape's width when it has one. */
export function textLines(
  text: string,
  size: number,
  width?: number,
): string[] {
  const ctx = measurer(size);
  const typed = text.split("\n");
  if (!ctx || width === undefined) return typed;
  const lines: string[] = [];
  for (const raw of typed) {
    let line = "";
    for (const word of raw.split(" ")) {
      const joined = line ? `${line} ${word}` : word;
      if (line && ctx.measureText(joined).width > width) {
        lines.push(line);
        line = word;
      } else {
        line = joined;
      }
    }
    lines.push(line);
  }
  return lines;
}

/** Longest typed line, unwrapped. */
export function textNaturalWidth(text: string, size: number): number {
  const ctx = measurer(size);
  if (!ctx) return 0;
  return Math.max(
    ...text.split("\n").map((line) => ctx.measureText(line).width),
  );
}

function measureText(
  text: string,
  size: number,
  width?: number,
): { w: number; h: number } {
  const ctx = measurer(size);
  if (!ctx) return { w: 0, h: 0 };
  const lines = textLines(text, size, width);
  const w =
    width ?? Math.max(...lines.map((line) => ctx.measureText(line).width));
  return { w, h: lines.length * size * TEXT_LINE };
}

export function shapeBBox(shape: Shape): Rect {
  switch (shape.kind) {
    case "rect":
    case "ellipse":
    case "pixelate":
      return shape.rect;
    case "arrow":
      return normalizeRect(shape.from, shape.to);
    case "pen": {
      const xs = shape.points.map((p) => p.x);
      const ys = shape.points.map((p) => p.y);
      return normalizeRect(
        { x: Math.min(...xs), y: Math.min(...ys) },
        { x: Math.max(...xs), y: Math.max(...ys) },
      );
    }
    case "text": {
      const size = measureText(shape.text, shape.size, shape.width);
      return shape.bg
        ? {
            x: shape.at.x - TEXT_BG_PAD_X,
            y: shape.at.y - TEXT_BG_PAD_Y,
            w: size.w + TEXT_BG_PAD_X * 2,
            h: size.h + TEXT_BG_PAD_Y * 2,
          }
        : { x: shape.at.x, y: shape.at.y, w: size.w, h: size.h };
    }
    case "counter":
      return {
        x: shape.at.x - COUNTER_RADIUS,
        y: shape.at.y - COUNTER_RADIUS,
        w: COUNTER_RADIUS * 2,
        h: COUNTER_RADIUS * 2,
      };
  }
}

function segmentDistance(p: Point, a: Point, b: Point): number {
  const abx = b.x - a.x;
  const aby = b.y - a.y;
  const lengthSq = abx * abx + aby * aby;
  const t = lengthSq
    ? Math.min(
        Math.max(((p.x - a.x) * abx + (p.y - a.y) * aby) / lengthSq, 0),
        1,
      )
    : 0;
  return Math.hypot(p.x - (a.x + abx * t), p.y - (a.y + aby * t));
}

const HIT_SLACK = 6;

export function hitShape(shape: Shape, point: Point): boolean {
  switch (shape.kind) {
    case "arrow":
      return segmentDistance(point, shape.from, shape.to) <= HIT_SLACK;
    case "pen":
      return shape.points.some(
        (at, index) =>
          index > 0 &&
          segmentDistance(point, shape.points[index - 1], at) <= HIT_SLACK,
      );
    default: {
      const box = shapeBBox(shape);
      return (
        point.x >= box.x - HIT_SLACK &&
        point.x <= box.x + box.w + HIT_SLACK &&
        point.y >= box.y - HIT_SLACK &&
        point.y <= box.y + box.h + HIT_SLACK
      );
    }
  }
}

export function translateShape(shape: Shape, dx: number, dy: number): Shape {
  switch (shape.kind) {
    case "rect":
    case "ellipse":
    case "pixelate":
      return {
        ...shape,
        rect: { ...shape.rect, x: shape.rect.x + dx, y: shape.rect.y + dy },
      };
    case "arrow":
      return {
        ...shape,
        from: { x: shape.from.x + dx, y: shape.from.y + dy },
        to: { x: shape.to.x + dx, y: shape.to.y + dy },
      };
    case "pen":
      return {
        ...shape,
        points: shape.points.map((p) => ({ x: p.x + dx, y: p.y + dy })),
      };
    case "text":
    case "counter":
      return { ...shape, at: { x: shape.at.x + dx, y: shape.at.y + dy } };
  }
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
      ctx.font = textFont(shape.size);
      ctx.textBaseline = "top";
      ctx.textAlign = "left";
      if (shape.bg) {
        const box = shapeBBox(shape);
        ctx.save();
        // Soft drop shadow lifts the pill off busy screenshots.
        ctx.shadowColor = "rgba(0, 0, 0, 0.28)";
        ctx.shadowBlur = 8;
        ctx.shadowOffsetY = 2;
        ctx.fillStyle = shape.color;
        ctx.beginPath();
        ctx.roundRect(box.x, box.y, box.w, box.h, 7);
        ctx.fill();
        ctx.restore();
        ctx.fillStyle = contrastInk(shape.color);
      } else {
        ctx.save();
        ctx.shadowColor = "rgba(0, 0, 0, 0.55)";
        ctx.shadowBlur = 3;
        ctx.fillStyle = shape.color;
      }
      let y = shape.at.y;
      for (const line of textLines(shape.text, shape.size, shape.width)) {
        ctx.fillText(line, shape.at.x, y);
        y += shape.size * TEXT_LINE;
      }
      if (!shape.bg) ctx.restore();
      return;
    }
    case "counter": {
      ctx.beginPath();
      ctx.arc(shape.at.x, shape.at.y, COUNTER_RADIUS, 0, Math.PI * 2);
      ctx.fillStyle = shape.color;
      ctx.fill();
      ctx.strokeStyle = "rgba(255, 255, 255, 0.85)";
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.font = `700 ${shape.n > 99 ? 11 : 13}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = contrastInk(shape.color);
      ctx.fillText(String(shape.n), shape.at.x, shape.at.y + 0.5);
      ctx.textAlign = "left";
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
