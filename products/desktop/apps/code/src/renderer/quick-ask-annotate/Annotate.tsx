import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";

const INK = "#f54e00";
const LINE_WIDTH = 3;
/** Long-edge cap for the exported PNG, well under the attachment size limit. */
const EXPORT_MAX_EDGE = 2000;
/** Drags smaller than this are clicks, not crops. */
const MIN_CROP_PX = 8;

interface Point {
  x: number;
  y: number;
}

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

type Tool = "rect" | "arrow" | "pen";

type Shape =
  | { kind: "rect"; rect: Rect }
  | { kind: "arrow"; from: Point; to: Point }
  | { kind: "pen"; points: Point[] };

function normalizeRect(a: Point, b: Point): Rect {
  return {
    x: Math.min(a.x, b.x),
    y: Math.min(a.y, b.y),
    w: Math.abs(a.x - b.x),
    h: Math.abs(a.y - b.y),
  };
}

function drawShape(ctx: CanvasRenderingContext2D, shape: Shape): void {
  ctx.strokeStyle = INK;
  ctx.fillStyle = INK;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  if (shape.kind === "rect") {
    const { x, y, w, h } = shape.rect;
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, 4);
    ctx.stroke();
    return;
  }
  if (shape.kind === "arrow") {
    const { from, to } = shape;
    const angle = Math.atan2(to.y - from.y, to.x - from.x);
    const head = Math.max(10, ctx.lineWidth * 3.5);
    ctx.beginPath();
    ctx.moveTo(from.x, from.y);
    ctx.lineTo(to.x, to.y);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(to.x, to.y);
    ctx.lineTo(
      to.x - head * Math.cos(angle - Math.PI / 6),
      to.y - head * Math.sin(angle - Math.PI / 6),
    );
    ctx.lineTo(
      to.x - head * Math.cos(angle + Math.PI / 6),
      to.y - head * Math.sin(angle + Math.PI / 6),
    );
    ctx.closePath();
    ctx.fill();
    return;
  }
  if (shape.points.length < 2) return;
  ctx.beginPath();
  ctx.moveTo(shape.points[0].x, shape.points[0].y);
  for (const point of shape.points.slice(1)) {
    ctx.lineTo(point.x, point.y);
  }
  ctx.stroke();
}

export function Annotate(): React.JSX.Element {
  const [shot, setShot] = useState<HTMLImageElement | null>(null);
  const [crop, setCrop] = useState<Rect | null>(null);
  const [tool, setTool] = useState<Tool>("rect");
  const [shapes, setShapes] = useState<Shape[]>([]);
  const [draft, setDraft] = useState<Shape | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const dragFrom = useRef<Point | null>(null);

  useEffect(() => {
    void window.quickAskAnnotate.shot().then((dataUrl) => {
      if (!dataUrl) {
        window.quickAskAnnotate.cancel();
        return;
      }
      const image = new Image();
      image.onload = () => setShot(image);
      image.src = dataUrl;
    });
  }, []);

  const finish = useCallback((): void => {
    if (!shot) return;
    const viewW = window.innerWidth;
    const viewH = window.innerHeight;
    const region = crop ?? { x: 0, y: 0, w: viewW, h: viewH };
    // View coordinates → shot pixels.
    const scaleX = shot.naturalWidth / viewW;
    const scaleY = shot.naturalHeight / viewH;
    const srcW = Math.max(1, Math.round(region.w * scaleX));
    const srcH = Math.max(1, Math.round(region.h * scaleY));
    const out = Math.min(1, EXPORT_MAX_EDGE / Math.max(srcW, srcH));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(srcW * out));
    canvas.height = Math.max(1, Math.round(srcH * out));
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(
      shot,
      region.x * scaleX,
      region.y * scaleY,
      srcW,
      srcH,
      0,
      0,
      canvas.width,
      canvas.height,
    );
    // Ink is drawn in view coordinates; move it into the cropped frame.
    ctx.scale(scaleX * out, scaleY * out);
    ctx.translate(-region.x, -region.y);
    ctx.lineWidth = LINE_WIDTH / ((scaleX + scaleY) / 2);
    for (const shape of shapes) {
      drawShape(ctx, shape);
    }
    window.quickAskAnnotate.done(canvas.toDataURL("image/png"));
  }, [shot, crop, shapes]);

  const undo = useCallback((): void => {
    setShapes((current) => current.slice(0, -1));
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") window.quickAskAnnotate.cancel();
      if (event.key === "Enter") finish();
      if (event.key === "z" && (event.metaKey || event.ctrlKey)) undo();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [finish, undo]);

  // One overlay canvas repaints the dim, the crop border, and the ink.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const draftCrop = !crop && draft?.kind === "rect" ? draft.rect : null;
    const hole = crop ?? draftCrop;
    ctx.fillStyle = "rgba(8, 8, 12, 0.55)";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (hole) {
      ctx.clearRect(hole.x, hole.y, hole.w, hole.h);
      ctx.strokeStyle = "rgba(255, 255, 255, 0.9)";
      ctx.lineWidth = 1.5;
      ctx.setLineDash([6, 4]);
      ctx.strokeRect(hole.x, hole.y, hole.w, hole.h);
      ctx.setLineDash([]);
    }
    ctx.lineWidth = LINE_WIDTH;
    for (const shape of shapes) {
      drawShape(ctx, shape);
    }
    if (crop && draft) {
      drawShape(ctx, draft);
    }
  }, [crop, shapes, draft]);

  const onMouseDown = useCallback(
    (event: React.MouseEvent): void => {
      if (event.button !== 0) return;
      const from = { x: event.clientX, y: event.clientY };
      dragFrom.current = from;
      if (!crop) {
        setDraft({ kind: "rect", rect: normalizeRect(from, from) });
      } else if (tool === "pen") {
        setDraft({ kind: "pen", points: [from] });
      } else if (tool === "arrow") {
        setDraft({ kind: "arrow", from, to: from });
      } else {
        setDraft({ kind: "rect", rect: normalizeRect(from, from) });
      }
    },
    [crop, tool],
  );

  const onMouseMove = useCallback((event: React.MouseEvent): void => {
    const from = dragFrom.current;
    if (!from) return;
    const to = { x: event.clientX, y: event.clientY };
    setDraft((current) => {
      if (!current) return current;
      if (current.kind === "pen") {
        return { kind: "pen", points: [...current.points, to] };
      }
      if (current.kind === "arrow") {
        return { kind: "arrow", from, to };
      }
      return { kind: "rect", rect: normalizeRect(from, to) };
    });
  }, []);

  const onMouseUp = useCallback((): void => {
    const from = dragFrom.current;
    dragFrom.current = null;
    if (!from) return;
    setDraft((current) => {
      if (!current) return null;
      if (!crop) {
        if (
          current.kind === "rect" &&
          (current.rect.w >= MIN_CROP_PX || current.rect.h >= MIN_CROP_PX)
        ) {
          setCrop(current.rect);
        }
        return null;
      }
      const tiny =
        current.kind === "rect" &&
        current.rect.w < MIN_CROP_PX &&
        current.rect.h < MIN_CROP_PX;
      if (!tiny) {
        setShapes((existing) => [...existing, current]);
      }
      return null;
    });
  }, [crop]);

  return (
    <div
      className="an-root"
      onMouseDown={onMouseDown}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
    >
      {shot && <img className="an-shot" src={shot.src} alt="" />}
      <canvas ref={canvasRef} className="an-overlay" />
      <div
        className="an-toolbar"
        onMouseDown={(event) => event.stopPropagation()}
      >
        {crop ? (
          <>
            {(
              [
                ["rect", "Box"],
                ["arrow", "Arrow"],
                ["pen", "Draw"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={tool === value ? "an-tool an-active" : "an-tool"}
                onClick={() => setTool(value)}
              >
                {label}
              </button>
            ))}
            <span className="an-sep" />
            <button
              type="button"
              className="an-tool"
              disabled={!shapes.length}
              onClick={undo}
            >
              Undo
            </button>
          </>
        ) : (
          <span className="an-hint">Drag to select an area</span>
        )}
        <span className="an-sep" />
        <button
          type="button"
          className="an-tool"
          onClick={() => window.quickAskAnnotate.cancel()}
        >
          Cancel
        </button>
        <button
          type="button"
          className="an-tool an-primary"
          onClick={finish}
          disabled={!shot}
        >
          Attach
        </button>
      </div>
    </div>
  );
}
