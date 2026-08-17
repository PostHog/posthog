import type React from "react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import {
  drawShape,
  LINE_WIDTH,
  normalizeRect,
  type Point,
  type Rect,
  type Shape,
  TEXT_FONT,
  type Tool,
} from "./shapes";
import { ToolIcon } from "./ToolIcon";

/** Long-edge cap for the exported PNG, well under the attachment size limit. */
const EXPORT_MAX_EDGE = 2000;
/** Drags smaller than this are clicks, not rects. */
const MIN_DRAG_PX = 6;
/** Hit radius around a resize handle, larger than its visual size. */
const HANDLE_HIT_PX = 12;

const COLORS = ["#ff4d1f", "#ffb224", "#3b82f6", "#ffffff"];

const TOOLS: { tool: Tool; label: string; key: string }[] = [
  { tool: "arrow", label: "Arrow", key: "A" },
  { tool: "rect", label: "Box", key: "R" },
  { tool: "ellipse", label: "Ellipse", key: "O" },
  { tool: "pen", label: "Draw", key: "P" },
  { tool: "text", label: "Text", key: "T" },
  { tool: "pixelate", label: "Pixelate", key: "X" },
];

type Handle = "nw" | "n" | "ne" | "e" | "se" | "s" | "sw" | "w";

const HANDLES: Handle[] = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];

const HANDLE_CURSORS: Record<Handle, string> = {
  nw: "nwse-resize",
  se: "nwse-resize",
  ne: "nesw-resize",
  sw: "nesw-resize",
  n: "ns-resize",
  s: "ns-resize",
  e: "ew-resize",
  w: "ew-resize",
};

function handlePoint(crop: Rect, handle: Handle): Point {
  const cx = crop.x + crop.w / 2;
  const cy = crop.y + crop.h / 2;
  switch (handle) {
    case "nw":
      return { x: crop.x, y: crop.y };
    case "n":
      return { x: cx, y: crop.y };
    case "ne":
      return { x: crop.x + crop.w, y: crop.y };
    case "e":
      return { x: crop.x + crop.w, y: cy };
    case "se":
      return { x: crop.x + crop.w, y: crop.y + crop.h };
    case "s":
      return { x: cx, y: crop.y + crop.h };
    case "sw":
      return { x: crop.x, y: crop.y + crop.h };
    case "w":
      return { x: crop.x, y: cy };
  }
}

function hitHandle(crop: Rect, point: Point): Handle | null {
  for (const handle of HANDLES) {
    const at = handlePoint(crop, handle);
    if (
      Math.abs(point.x - at.x) <= HANDLE_HIT_PX &&
      Math.abs(point.y - at.y) <= HANDLE_HIT_PX
    ) {
      return handle;
    }
  }
  return null;
}

function resizeCrop(crop: Rect, handle: Handle, to: Point): Rect {
  let { x, y } = crop;
  let right = crop.x + crop.w;
  let bottom = crop.y + crop.h;
  if (handle.includes("w")) x = to.x;
  if (handle.includes("e")) right = to.x;
  if (handle.includes("n")) y = to.y;
  if (handle.includes("s")) bottom = to.y;
  return normalizeRect({ x, y }, { x: right, y: bottom });
}

function clampCrop(crop: Rect): Rect {
  const w = Math.min(crop.w, window.innerWidth);
  const h = Math.min(crop.h, window.innerHeight);
  return {
    x: Math.min(Math.max(crop.x, 0), window.innerWidth - w),
    y: Math.min(Math.max(crop.y, 0), window.innerHeight - h),
    w,
    h,
  };
}

function inside(rect: Rect, point: Point): boolean {
  return (
    point.x >= rect.x &&
    point.x <= rect.x + rect.w &&
    point.y >= rect.y &&
    point.y <= rect.y + rect.h
  );
}

type Drag =
  | { mode: "select"; from: Point }
  | { mode: "draw"; from: Point }
  | { mode: "move"; from: Point; orig: Rect }
  | { mode: "resize"; handle: Handle };

export function Annotate(): React.JSX.Element {
  const [shot, setShot] = useState<HTMLImageElement | null>(null);
  const [crop, setCrop] = useState<Rect | null>(null);
  const [tool, setTool] = useState<Tool>("arrow");
  const [color, setColor] = useState(COLORS[0]);
  const [shapes, setShapes] = useState<Shape[]>([]);
  const [redoStack, setRedoStack] = useState<Shape[]>([]);
  const [draft, setDraft] = useState<Shape | null>(null);
  const [textDraft, setTextDraft] = useState<Point | null>(null);
  const [cursor, setCursor] = useState("crosshair");
  const [spaceHeld, setSpaceHeld] = useState(false);
  const [toolbarShift, setToolbarShift] = useState({ dx: 0, above: false });
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const toolbarRef = useRef<HTMLDivElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const drag = useRef<Drag | null>(null);

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

  const scaleX = shot ? shot.naturalWidth / window.innerWidth : 1;
  const scaleY = shot ? shot.naturalHeight / window.innerHeight : 1;

  const pushShape = useCallback((shape: Shape): void => {
    setShapes((current) => [...current, shape]);
    setRedoStack([]);
  }, []);

  const commitText = useCallback(
    (keep: boolean): void => {
      const at = textDraft;
      const value = textRef.current?.value ?? "";
      setTextDraft(null);
      if (keep && at && value.trim()) {
        pushShape({ kind: "text", at, text: value.trimEnd(), color });
      }
    },
    [textDraft, color, pushShape],
  );

  const undo = useCallback((): void => {
    setShapes((current) => {
      const last = current.at(-1);
      if (last) setRedoStack((stack) => [...stack, last]);
      return current.slice(0, -1);
    });
  }, []);

  const redo = useCallback((): void => {
    setRedoStack((stack) => {
      const last = stack.at(-1);
      if (last) setShapes((current) => [...current, last]);
      return stack.slice(0, -1);
    });
  }, []);

  const finish = useCallback((): void => {
    if (!shot) return;
    if (textDraft) commitText(true);
    const region = crop ?? {
      x: 0,
      y: 0,
      w: window.innerWidth,
      h: window.innerHeight,
    };
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
    // Ink lives in view coordinates; the transform carries stroke widths and
    // text sizes into shot pixels so the export matches the preview.
    ctx.scale(scaleX * out, scaleY * out);
    ctx.translate(-region.x, -region.y);
    const env = { image: shot, sx: scaleX, sy: scaleY };
    for (const shape of shapes) {
      drawShape(ctx, shape, env);
    }
    window.quickAskAnnotate.done(canvas.toDataURL("image/png"));
  }, [shot, crop, shapes, scaleX, scaleY, textDraft, commitText]);

  // Keyboard: tools, undo/redo, nudge and resize the selection, finish.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        if (textDraft) {
          commitText(false);
        } else {
          window.quickAskAnnotate.cancel();
        }
        return;
      }
      // The text editor owns every other key while open.
      if (textDraft) return;
      if (event.key === "Enter") {
        finish();
        return;
      }
      if ((event.metaKey || event.ctrlKey) && event.key === "z") {
        event.preventDefault();
        if (event.shiftKey) redo();
        else undo();
        return;
      }
      if (event.key === " ") {
        setSpaceHeld(true);
        return;
      }
      if (event.key.startsWith("Arrow") && crop) {
        event.preventDefault();
        const step = event.altKey ? 10 : 1;
        const dx =
          event.key === "ArrowLeft"
            ? -step
            : event.key === "ArrowRight"
              ? step
              : 0;
        const dy =
          event.key === "ArrowUp"
            ? -step
            : event.key === "ArrowDown"
              ? step
              : 0;
        setCrop((current) => {
          if (!current) return current;
          if (event.shiftKey) {
            return clampCrop({
              ...current,
              w: Math.max(MIN_DRAG_PX, current.w + dx),
              h: Math.max(MIN_DRAG_PX, current.h + dy),
            });
          }
          return clampCrop({
            ...current,
            x: current.x + dx,
            y: current.y + dy,
          });
        });
        return;
      }
      const byKey = TOOLS.find(
        (entry) => entry.key.toLowerCase() === event.key.toLowerCase(),
      );
      if (byKey && !event.metaKey && !event.ctrlKey) {
        setTool(byKey.tool);
      }
    };
    const onKeyUp = (event: KeyboardEvent): void => {
      if (event.key === " ") setSpaceHeld(false);
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [crop, textDraft, commitText, finish, undo, redo]);

  // One overlay canvas repaints the dim, the selection frame, and the ink.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !shot) return;
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const draftCrop =
      !crop && drag.current?.mode === "select" && draft?.kind === "rect"
        ? draft.rect
        : null;
    const hole = crop ?? draftCrop;
    ctx.fillStyle = "rgba(6, 7, 10, 0.52)";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (hole) {
      ctx.clearRect(hole.x, hole.y, hole.w, hole.h);
    }
    const env = { image: shot, sx: scaleX, sy: scaleY };
    for (const shape of shapes) {
      drawShape(ctx, shape, env);
    }
    if (crop && draft) {
      drawShape(ctx, draft, env);
    }
    if (hole) {
      // Hairline light frame with a soft halo, readable on any content.
      ctx.strokeStyle = "rgba(0, 0, 0, 0.55)";
      ctx.lineWidth = 3;
      ctx.strokeRect(hole.x - 1, hole.y - 1, hole.w + 2, hole.h + 2);
      ctx.strokeStyle = "rgba(255, 255, 255, 0.95)";
      ctx.lineWidth = 1.5;
      ctx.strokeRect(hole.x - 0.75, hole.y - 0.75, hole.w + 1.5, hole.h + 1.5);
    }
    if (crop) {
      for (const handle of HANDLES) {
        const at = handlePoint(crop, handle);
        ctx.beginPath();
        ctx.arc(at.x, at.y, 4.5, 0, Math.PI * 2);
        ctx.fillStyle = "#ffffff";
        ctx.fill();
        ctx.strokeStyle = "rgba(0, 0, 0, 0.45)";
        ctx.lineWidth = 1;
        ctx.stroke();
      }
    }
  }, [shot, crop, shapes, draft, scaleX, scaleY]);

  // Keep the toolbar inside the viewport: centered under the selection,
  // flipped above it when there is no room below.
  useLayoutEffect(() => {
    const toolbar = toolbarRef.current;
    if (!toolbar || !crop) return;
    const width = toolbar.offsetWidth;
    const height = toolbar.offsetHeight;
    const centered = crop.x + crop.w / 2 - width / 2;
    const left = Math.min(
      Math.max(centered, 10),
      window.innerWidth - width - 10,
    );
    const above = crop.y + crop.h + height + 26 > window.innerHeight;
    setToolbarShift({ dx: left - centered, above });
  }, [crop]);

  const pointOf = (event: React.MouseEvent): Point => ({
    x: event.clientX,
    y: event.clientY,
  });

  const onMouseDown = useCallback(
    (event: React.MouseEvent): void => {
      if (event.button !== 0) return;
      const from = pointOf(event);
      if (textDraft) {
        commitText(true);
        return;
      }
      if (!crop) {
        drag.current = { mode: "select", from };
        setDraft({ kind: "rect", rect: normalizeRect(from, from), color });
        return;
      }
      const handle = hitHandle(crop, from);
      if (handle) {
        drag.current = { mode: "resize", handle };
        return;
      }
      if (spaceHeld && inside(crop, from)) {
        drag.current = { mode: "move", from, orig: crop };
        return;
      }
      if (tool === "text") {
        setTextDraft(from);
        return;
      }
      drag.current = { mode: "draw", from };
      setDraft(
        tool === "pen"
          ? { kind: "pen", points: [from], color }
          : tool === "arrow"
            ? { kind: "arrow", from, to: from, color }
            : tool === "pixelate"
              ? { kind: "pixelate", rect: normalizeRect(from, from) }
              : { kind: tool, rect: normalizeRect(from, from), color },
      );
    },
    [crop, tool, color, spaceHeld, textDraft, commitText],
  );

  const onMouseMove = useCallback(
    (event: React.MouseEvent): void => {
      const to = pointOf(event);
      const active = drag.current;
      if (!active) {
        // Hover feedback only: resize cursors on handles, move while Space.
        if (crop) {
          const handle = hitHandle(crop, to);
          setCursor(
            handle
              ? HANDLE_CURSORS[handle]
              : spaceHeld && inside(crop, to)
                ? "grab"
                : tool === "text"
                  ? "text"
                  : "crosshair",
          );
        }
        return;
      }
      if (active.mode === "resize") {
        setCrop((current) =>
          current ? clampCrop(resizeCrop(current, active.handle, to)) : current,
        );
        return;
      }
      if (active.mode === "move") {
        setCrop(
          clampCrop({
            ...active.orig,
            x: active.orig.x + to.x - active.from.x,
            y: active.orig.y + to.y - active.from.y,
          }),
        );
        return;
      }
      setDraft((current) => {
        if (!current) return current;
        if (current.kind === "pen") {
          return { ...current, points: [...current.points, to] };
        }
        if (current.kind === "arrow") {
          return { ...current, to };
        }
        return { ...current, rect: normalizeRect(active.from, to) };
      });
    },
    [crop, tool, spaceHeld],
  );

  const onMouseUp = useCallback((): void => {
    const active = drag.current;
    drag.current = null;
    if (!active) return;
    if (active.mode === "resize" || active.mode === "move") return;
    setDraft((current) => {
      if (!current) return null;
      if (active.mode === "select") {
        if (
          current.kind === "rect" &&
          (current.rect.w >= MIN_DRAG_PX || current.rect.h >= MIN_DRAG_PX)
        ) {
          setCrop(clampCrop(current.rect));
        }
        return null;
      }
      const tiny =
        "rect" in current &&
        current.rect.w < MIN_DRAG_PX &&
        current.rect.h < MIN_DRAG_PX;
      const short =
        current.kind === "arrow" &&
        Math.hypot(
          current.to.x - current.from.x,
          current.to.y - current.from.y,
        ) < MIN_DRAG_PX;
      if (!tiny && !short) {
        pushShape(current);
      }
      return null;
    });
  }, [pushShape]);

  const exportW = crop ? Math.round(crop.w * scaleX) : 0;
  const exportH = crop ? Math.round(crop.h * scaleY) : 0;

  return (
    <div
      className="an-root"
      style={{ cursor }}
      onMouseDown={onMouseDown}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
    >
      {shot && <img className="an-shot" src={shot.src} alt="" />}
      <canvas ref={canvasRef} className="an-overlay" />

      {!crop && (
        <div className="an-hint">
          Drag to select an area
          <span className="an-hint-keys">
            <kbd>esc</kbd> to cancel
          </span>
        </div>
      )}

      {crop && (
        <div
          className="an-dims"
          style={{
            left: Math.min(
              Math.max(crop.x + crop.w - 92, 10),
              window.innerWidth - 100,
            ),
            top: crop.y > 34 ? crop.y - 30 : crop.y + 8,
          }}
        >
          {exportW} × {exportH}
        </div>
      )}

      {crop && (
        <div
          ref={toolbarRef}
          className="an-toolbar"
          style={{
            left: crop.x + crop.w / 2 + toolbarShift.dx,
            top: toolbarShift.above
              ? Math.max(crop.y - 62, 10)
              : crop.y + crop.h + 14,
          }}
          onMouseDown={(event) => event.stopPropagation()}
        >
          {TOOLS.map((entry) => (
            <button
              key={entry.tool}
              type="button"
              aria-label={`${entry.label} (${entry.key})`}
              title={`${entry.label} — ${entry.key}`}
              className={tool === entry.tool ? "an-tool an-active" : "an-tool"}
              onClick={() => setTool(entry.tool)}
            >
              <ToolIcon tool={entry.tool} />
            </button>
          ))}
          <span className="an-sep" />
          {COLORS.map((value) => (
            <button
              key={value}
              type="button"
              aria-label={`Ink ${value}`}
              className={value === color ? "an-color an-color-on" : "an-color"}
              style={{ background: value }}
              onClick={() => setColor(value)}
            />
          ))}
          <span className="an-sep" />
          <button
            type="button"
            aria-label="Undo (⌘Z)"
            title="Undo — ⌘Z"
            className="an-tool"
            disabled={!shapes.length}
            onClick={undo}
          >
            <ToolIcon tool="undo" />
          </button>
          <button
            type="button"
            aria-label="Redo (⇧⌘Z)"
            title="Redo — ⇧⌘Z"
            className="an-tool"
            disabled={!redoStack.length}
            onClick={redo}
          >
            <ToolIcon tool="redo" />
          </button>
          <span className="an-sep" />
          <button
            type="button"
            className="an-cancel"
            onClick={() => window.quickAskAnnotate.cancel()}
          >
            Cancel
          </button>
          <button type="button" className="an-attach" onClick={finish}>
            Attach
            <kbd>⏎</kbd>
          </button>
        </div>
      )}

      {textDraft && (
        <textarea
          ref={textRef}
          className="an-text-input"
          style={{
            left: textDraft.x,
            top: textDraft.y,
            color,
            font: TEXT_FONT,
            caretColor: color,
            textShadow: `0 0 ${LINE_WIDTH}px rgba(0,0,0,0.4)`,
          }}
          rows={1}
          placeholder="Type…"
          // biome-ignore lint/a11y/noAutofocus: the tool just placed the caret
          autoFocus
          spellCheck={false}
          onMouseDown={(event) => event.stopPropagation()}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              commitText(true);
            }
          }}
          onInput={(event) => {
            const el = event.currentTarget;
            el.style.height = "auto";
            el.style.height = `${el.scrollHeight}px`;
            el.style.width = "auto";
            el.style.width = `${Math.min(el.scrollWidth + 12, window.innerWidth - textDraft.x - 10)}px`;
          }}
        />
      )}
    </div>
  );
}
