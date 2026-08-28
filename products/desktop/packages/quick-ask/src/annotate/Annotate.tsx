import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { annotateHost } from "./host-bridge";
import {
  contrastInk,
  drawShape,
  hitShape,
  normalizeRect,
  type Point,
  type Rect,
  type Shape,
  shapeBBox,
  TEXT_BG_PAD_X,
  TEXT_BG_PAD_Y,
  TEXT_LINE,
  TEXT_MAX_SIZE,
  TEXT_MIN_SIZE,
  TEXT_MIN_WIDTH,
  TEXT_SIZE,
  type Tool,
  textFont,
  textNaturalWidth,
  translateShape,
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
  { tool: "select", label: "Select", key: "V" },
  { tool: "crop", label: "Crop", key: "C" },
  { tool: "arrow", label: "Arrow", key: "A" },
  { tool: "rect", label: "Box", key: "R" },
  { tool: "ellipse", label: "Ellipse", key: "O" },
  { tool: "pen", label: "Draw", key: "P" },
  { tool: "text", label: "Text", key: "T" },
  { tool: "counter", label: "Counter", key: "N" },
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

/** Shapes with snapshot history, so delete/move/recolor undo cleanly. */
interface Doc {
  past: Shape[][];
  shapes: Shape[];
  future: Shape[][];
}

type Drag =
  | { mode: "select"; from: Point }
  | { mode: "draw"; from: Point }
  | { mode: "move"; from: Point; orig: Rect }
  | { mode: "resize"; handle: Handle }
  | {
      mode: "move-shape";
      from: Point;
      index: number;
      orig: Shape[];
      moved: boolean;
    }
  | {
      mode: "resize-shape";
      index: number;
      handle: string;
      orig: Shape[];
      moved: boolean;
    };

function pointOf(event: React.MouseEvent): Point {
  return { x: event.clientX, y: event.clientY };
}

/**
 * Wrap width for new text: the room left inside the selection, capped at a
 * readable line length so labels never run the full width of a large crop.
 */
function textWrapCap(x: number, crop: Rect, bg: boolean): number {
  const pads = bg ? TEXT_BG_PAD_X * 2 : 0;
  const room = Math.max(crop.x + crop.w, x + 160) - x - pads - 8;
  const readable = Math.max(260, Math.min(520, crop.w * 0.6));
  return Math.max(TEXT_MIN_WIDTH, Math.min(room, readable));
}

interface ShapeHandle {
  id: string;
  at: Point;
  cursor: string;
}

/** Resize handles: corners and edges for boxes, endpoints for arrows,
 * wrap-width side handles for text. */
function shapeHandles(shape: Shape): ShapeHandle[] {
  switch (shape.kind) {
    case "rect":
    case "ellipse":
    case "pixelate":
      return HANDLES.map((handle) => ({
        id: handle,
        at: handlePoint(shape.rect, handle),
        cursor: HANDLE_CURSORS[handle],
      }));
    case "arrow":
      return [
        { id: "from", at: shape.from, cursor: "move" },
        { id: "to", at: shape.to, cursor: "move" },
      ];
    case "text": {
      const box = shapeBBox(shape);
      const cy = box.y + box.h / 2;
      return [
        { id: "w", at: { x: box.x - 5, y: cy }, cursor: "ew-resize" },
        { id: "e", at: { x: box.x + box.w + 5, y: cy }, cursor: "ew-resize" },
      ];
    }
    default:
      return [];
  }
}

function hitShapeHandle(shape: Shape, point: Point): ShapeHandle | null {
  for (const handle of shapeHandles(shape)) {
    if (
      Math.abs(point.x - handle.at.x) <= HANDLE_HIT_PX &&
      Math.abs(point.y - handle.at.y) <= HANDLE_HIT_PX
    ) {
      return handle;
    }
  }
  return null;
}

/** A resize-handle drag applied to the shape that grabbed it. */
function resizeShape(shape: Shape, handle: string, to: Point): Shape {
  switch (shape.kind) {
    case "rect":
    case "ellipse":
    case "pixelate":
      return { ...shape, rect: resizeCrop(shape.rect, handle as Handle, to) };
    case "arrow":
      // Endpoint drags re-aim just that end of the line.
      return handle === "from" ? { ...shape, from: to } : { ...shape, to };
    case "text": {
      const pad = shape.bg ? TEXT_BG_PAD_X : 0;
      const box = shapeBBox(shape);
      const contentW = box.w - pad * 2;
      if (handle === "e") {
        const width = Math.max(to.x - 5 - pad - shape.at.x, TEXT_MIN_WIDTH);
        return { ...shape, width };
      }
      const right = shape.at.x + contentW;
      const x = Math.min(to.x + 5 + pad, right - TEXT_MIN_WIDTH);
      return { ...shape, at: { ...shape.at, x }, width: right - x };
    }
    default:
      return shape;
  }
}

export function Annotate(): React.JSX.Element {
  const [shot, setShot] = useState<HTMLImageElement | null>(null);
  const [crop, setCrop] = useState<Rect | null>(() => ({
    x: 0,
    y: 0,
    w: window.innerWidth,
    h: window.innerHeight,
  }));
  const [tool, setTool] = useState<Tool>("select");
  const [color, setColor] = useState(COLORS[0]);
  const [doc, setDoc] = useState<Doc>({ past: [], shapes: [], future: [] });
  const [selected, setSelected] = useState<number | null>(null);
  const [textBg, setTextBg] = useState(true);
  const [textSize, setTextSize] = useState(TEXT_SIZE);
  const [draft, setDraft] = useState<Shape | null>(null);
  const [textDraft, setTextDraft] = useState<Point | null>(null);
  const [cursor, setCursor] = useState("default");
  const [spaceHeld, setSpaceHeld] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const drag = useRef<Drag | null>(null);

  const { shapes } = doc;

  // Focus the text editor once it mounts; autoFocus races the mousedown.
  useEffect(() => {
    if (textDraft) {
      requestAnimationFrame(() => textRef.current?.focus());
    }
  }, [textDraft]);

  useEffect(() => {
    void annotateHost()
      .shot()
      .then((dataUrl) => {
        if (!dataUrl) {
          annotateHost().cancel();
          return;
        }
        const image = new Image();
        image.onload = () => setShot(image);
        image.src = dataUrl;
      });
  }, []);

  const scaleX = shot ? shot.naturalWidth / window.innerWidth : 1;
  const scaleY = shot ? shot.naturalHeight / window.innerHeight : 1;

  const commit = useCallback((updater: (shapes: Shape[]) => Shape[]): void => {
    setDoc((current) => ({
      past: [...current.past, current.shapes],
      shapes: updater(current.shapes),
      future: [],
    }));
  }, []);

  const pushShape = useCallback(
    (shape: Shape): void => {
      commit((current) => [...current, shape]);
      setSelected(shapes.length);
    },
    [commit, shapes.length],
  );

  const deleteSelected = useCallback((): void => {
    if (selected === null) return;
    commit((current) => current.filter((_, index) => index !== selected));
    setSelected(null);
  }, [selected, commit]);

  // Builds the shape for the open text draft, or null when there is no draft
  // or its value is blank. Shared by commitText and the synchronous export in
  // finish, so the exported PNG and the committed shape can never diverge.
  const buildTextShape = useCallback((): Shape | null => {
    const at = textDraft;
    const value = textRef.current?.value ?? "";
    if (!at || !value.trim()) return null;
    const text = value.trimEnd();
    const cap = crop ? textWrapCap(at.x, crop, textBg) : undefined;
    const wraps = cap !== undefined && textNaturalWidth(text, textSize) > cap;
    return {
      kind: "text",
      at,
      text,
      color,
      bg: textBg,
      size: textSize,
      ...(wraps ? { width: cap } : {}),
    };
  }, [textDraft, crop, color, textBg, textSize]);

  const commitText = useCallback(
    (keep: boolean): void => {
      const shape = keep ? buildTextShape() : null;
      setTextDraft(null);
      if (shape) {
        pushShape(shape);
        // The usual next step is placing the label, so hand over the
        // select tool with the fresh label already selected.
        setTool("select");
      }
    },
    [buildTextShape, pushShape],
  );

  const undo = useCallback((): void => {
    setSelected(null);
    setDoc((current) => {
      const previous = current.past.at(-1);
      if (!previous) return current;
      return {
        past: current.past.slice(0, -1),
        shapes: previous,
        future: [...current.future, current.shapes],
      };
    });
  }, []);

  const redo = useCallback((): void => {
    setSelected(null);
    setDoc((current) => {
      const next = current.future.at(-1);
      if (!next) return current;
      return {
        past: [...current.past, current.shapes],
        shapes: next,
        future: current.future.slice(0, -1),
      };
    });
  }, []);

  // Swatches recolor the selection when there is one; either way they set
  // the ink for what comes next.
  const pickColor = useCallback(
    (value: string): void => {
      setColor(value);
      if (selected !== null && shapes[selected]?.kind !== "pixelate") {
        commit((current) =>
          current.map((shape, index) =>
            index === selected && shape.kind !== "pixelate"
              ? { ...shape, color: value }
              : shape,
          ),
        );
      }
    },
    [selected, shapes, commit],
  );

  const toggleTextBg = useCallback((): void => {
    setTextBg((current) => !current);
    if (selected !== null && shapes[selected]?.kind === "text") {
      commit((current) =>
        current.map((shape, index) =>
          index === selected && shape.kind === "text"
            ? { ...shape, bg: !shape.bg }
            : shape,
        ),
      );
    }
  }, [selected, shapes, commit]);

  // The slider's drag is one undo step: grab snapshots the pre-drag shapes and
  // release records them as a single entry. A keyboard change on the focused
  // slider fires onChange with no grab, so pickTextSize commits it on its own.
  const sizeDragOrig = useRef<Shape[] | null>(null);

  const pickTextSize = useCallback(
    (value: number): void => {
      setTextSize(value);
      if (selected === null || shapes[selected]?.kind !== "text") return;
      const applySize = (list: Shape[]): Shape[] =>
        list.map((shape, index) =>
          index === selected && shape.kind === "text"
            ? { ...shape, size: value }
            : shape,
        );
      if (sizeDragOrig.current) {
        // Mid-drag: fold into the single entry release will record.
        setDoc((current) => ({
          ...current,
          shapes: applySize(current.shapes),
        }));
      } else {
        // Keyboard: its own undo step, and clears redo like the sibling
        // color and background controls already do.
        commit(applySize);
      }
    },
    [selected, shapes, commit],
  );

  const grabTextSize = useCallback((): void => {
    sizeDragOrig.current =
      selected !== null && shapes[selected]?.kind === "text" ? shapes : null;
  }, [selected, shapes]);

  const releaseTextSize = useCallback((): void => {
    const orig = sizeDragOrig.current;
    sizeDragOrig.current = null;
    if (!orig) return;
    setDoc((current) =>
      current.shapes === orig
        ? current
        : { ...current, past: [...current.past, orig], future: [] },
    );
  }, []);

  const finish = useCallback((): void => {
    if (!shot) return;
    // Build the open draft synchronously: commitText only schedules a state
    // update, so `shapes` in this same tick would not yet hold the new label
    // and the export would drop it (e.g. clicking Attach without pressing
    // Enter first).
    const pending = textDraft ? buildTextShape() : null;
    if (textDraft) commitText(true);
    const exportShapes = pending ? [...shapes, pending] : shapes;
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
    for (const shape of exportShapes) {
      drawShape(ctx, shape, env);
    }
    annotateHost().done(canvas.toDataURL("image/png"));
  }, [
    shot,
    crop,
    shapes,
    scaleX,
    scaleY,
    textDraft,
    buildTextShape,
    commitText,
  ]);

  // Keyboard: tools, undo/redo, delete, nudge and resize, finish.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        if (textDraft) {
          commitText(false);
        } else if (selected !== null) {
          setSelected(null);
        } else {
          annotateHost().cancel();
        }
        return;
      }
      // The text editor or a focused control owns every other key.
      if (textDraft) return;
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" || target.tagName === "TEXTAREA")
      ) {
        return;
      }
      if (event.key === "Enter") {
        finish();
        return;
      }
      // Shift makes the browser report the key as "Z"; lowercase it so the
      // redo half (Cmd/Ctrl+Shift+Z) reaches this branch at all.
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) redo();
        else undo();
        return;
      }
      if (
        (event.key === "Backspace" || event.key === "Delete") &&
        selected !== null
      ) {
        event.preventDefault();
        deleteSelected();
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
  }, [
    crop,
    textDraft,
    selected,
    commitText,
    finish,
    undo,
    redo,
    deleteSelected,
  ]);

  // One overlay canvas repaints the dim, the selection frame, and the ink.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !shot) return;
    // Render at device resolution; 1x looks soft on Retina screens.
    const dpr = window.devicePixelRatio || 1;
    canvas.width = window.innerWidth * dpr;
    canvas.height = window.innerHeight * dpr;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
    const draftCrop =
      !crop && drag.current?.mode === "select" && draft?.kind === "rect"
        ? draft.rect
        : null;
    const hole = crop ?? draftCrop;
    ctx.fillStyle = "rgba(6, 7, 10, 0.52)";
    ctx.fillRect(0, 0, window.innerWidth, window.innerHeight);
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
    const active = selected !== null ? shapes[selected] : null;
    if (active) {
      const box = shapeBBox(active);
      ctx.strokeStyle = "rgba(255, 255, 255, 0.85)";
      ctx.lineWidth = 1;
      ctx.setLineDash([5, 4]);
      ctx.strokeRect(box.x - 5, box.y - 5, box.w + 10, box.h + 10);
      ctx.setLineDash([]);
      for (const handle of shapeHandles(active)) {
        ctx.beginPath();
        ctx.arc(handle.at.x, handle.at.y, 4.5, 0, Math.PI * 2);
        ctx.fillStyle = "#ffffff";
        ctx.fill();
        ctx.strokeStyle = "rgba(0, 0, 0, 0.45)";
        ctx.lineWidth = 1;
        ctx.stroke();
      }
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
  }, [shot, crop, shapes, draft, selected, scaleX, scaleY]);

  const topShapeAt = useCallback(
    (point: Point): number | null => {
      for (let index = shapes.length - 1; index >= 0; index--) {
        if (hitShape(shapes[index], point)) return index;
      }
      return null;
    },
    [shapes],
  );

  const onMouseDown = useCallback(
    (event: React.MouseEvent): void => {
      if (event.button !== 0) return;
      const from = pointOf(event);
      if (textDraft) {
        commitText(true);
        return;
      }
      if (!crop || tool === "crop") {
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
      if (tool === "select") {
        const active = selected !== null ? shapes[selected] : null;
        const handleHit = active ? hitShapeHandle(active, from) : null;
        if (handleHit && selected !== null) {
          drag.current = {
            mode: "resize-shape",
            index: selected,
            handle: handleHit.id,
            orig: shapes,
            moved: false,
          };
          return;
        }
        const index = topShapeAt(from);
        setSelected(index);
        if (index !== null) {
          drag.current = {
            mode: "move-shape",
            from,
            index,
            orig: shapes,
            moved: false,
          };
        }
        return;
      }
      setSelected(null);
      if (tool === "text") {
        // The mousedown's default focus handling would steal focus from the
        // editor right after it mounts.
        event.preventDefault();
        setTextDraft(from);
        return;
      }
      if (tool === "counter") {
        const next =
          Math.max(
            0,
            ...shapes.map((shape) => (shape.kind === "counter" ? shape.n : 0)),
          ) + 1;
        pushShape({ kind: "counter", at: from, n: next, color });
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
    [
      crop,
      tool,
      color,
      spaceHeld,
      textDraft,
      shapes,
      selected,
      commitText,
      topShapeAt,
      pushShape,
    ],
  );

  const onMouseMove = useCallback(
    (event: React.MouseEvent): void => {
      const to = pointOf(event);
      const active = drag.current;
      if (!active) {
        // Hover feedback only: resize cursors on handles, move over shapes.
        if (crop) {
          const handle = hitHandle(crop, to);
          const activeShape = selected !== null ? shapes[selected] : null;
          const shapeHandleHit =
            tool === "select" && activeShape
              ? hitShapeHandle(activeShape, to)
              : null;
          setCursor(
            handle
              ? HANDLE_CURSORS[handle]
              : shapeHandleHit
                ? shapeHandleHit.cursor
                : spaceHeld && inside(crop, to)
                  ? "grab"
                  : tool === "select"
                    ? topShapeAt(to) !== null
                      ? "move"
                      : "default"
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
      if (active.mode === "move-shape") {
        active.moved = true;
        const dx = to.x - active.from.x;
        const dy = to.y - active.from.y;
        setDoc((current) => ({
          ...current,
          shapes: active.orig.map((shape, index) =>
            index === active.index ? translateShape(shape, dx, dy) : shape,
          ),
        }));
        return;
      }
      if (active.mode === "resize-shape") {
        active.moved = true;
        setDoc((current) => ({
          ...current,
          shapes: active.orig.map((shape, index) =>
            index === active.index
              ? resizeShape(shape, active.handle, to)
              : shape,
          ),
        }));
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
        if ("rect" in current) {
          return { ...current, rect: normalizeRect(active.from, to) };
        }
        return current;
      });
    },
    [crop, tool, spaceHeld, selected, shapes, topShapeAt],
  );

  const onMouseUp = useCallback((): void => {
    const active = drag.current;
    drag.current = null;
    if (!active) return;
    if (active.mode === "resize" || active.mode === "move") return;
    if (active.mode === "move-shape" || active.mode === "resize-shape") {
      // One history entry per completed move.
      if (active.moved) {
        setDoc((current) => ({
          past: [...current.past, active.orig],
          shapes: current.shapes,
          future: [],
        }));
      }
      return;
    }
    setDraft((current) => {
      if (!current) return null;
      if (active.mode === "select") {
        if (
          current.kind === "rect" &&
          (current.rect.w >= MIN_DRAG_PX || current.rect.h >= MIN_DRAG_PX)
        ) {
          setCrop(clampCrop(current.rect));
          setTool("select");
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
        // The usual next step is adjusting the fresh shape.
        setTool("select");
      }
      return null;
    });
  }, [pushShape]);

  const exportW = crop ? Math.round(crop.w * scaleX) : 0;
  const exportH = crop ? Math.round(crop.h * scaleY) : 0;
  const selectedShape = selected !== null ? shapes[selected] : null;
  const selectedText = selectedShape?.kind === "text" ? selectedShape : null;
  const showTextOptions = tool === "text" || selectedText !== null;
  const textBgOn = selectedText ? selectedText.bg : textBg;
  const textSizeOn = selectedText ? selectedText.size : textSize;
  // The editor wraps live at the same width the committed shape would get.
  const editorCap =
    textDraft && crop
      ? textWrapCap(textDraft.x, crop, textBg) +
        (textBg ? TEXT_BG_PAD_X * 2 : 0) +
        6
      : null;

  return (
    <div
      role="application"
      aria-label="Screenshot annotator"
      className="an-root"
      style={{ cursor }}
      onMouseDown={onMouseDown}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
    >
      {shot && <img className="an-shot" src={shot.src} alt="" />}
      <canvas ref={canvasRef} className="an-overlay" />

      {(!crop || tool === "crop") && (
        <div className="an-hint">
          Drag to select an area
          <span className="an-hint-keys">
            <kbd>esc</kbd> to cancel
          </span>
        </div>
      )}

      {crop && (
        <div
          role="toolbar"
          className="an-toolbar"
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
              onClick={() => pickColor(value)}
            />
          ))}
          <span className="an-sep" />
          {selectedShape && (
            <button
              type="button"
              aria-label="Delete (⌫)"
              title="Delete — ⌫"
              className="an-tool"
              onClick={deleteSelected}
            >
              <ToolIcon tool="trash" />
            </button>
          )}
          <button
            type="button"
            aria-label="Undo (⌘Z)"
            title="Undo — ⌘Z"
            className="an-tool"
            disabled={!doc.past.length}
            onClick={undo}
          >
            <ToolIcon tool="undo" />
          </button>
          <button
            type="button"
            aria-label="Redo (⇧⌘Z)"
            title="Redo — ⇧⌘Z"
            className="an-tool"
            disabled={!doc.future.length}
            onClick={redo}
          >
            <ToolIcon tool="redo" />
          </button>
          <span className="an-sep" />
          <span className="an-size">
            {exportW} × {exportH}
          </span>
          <span className="an-sep" />
          <button
            type="button"
            className="an-cancel"
            onClick={() => annotateHost().cancel()}
          >
            Cancel
          </button>
          <button type="button" className="an-attach" onClick={finish}>
            Attach
            <kbd>⏎</kbd>
          </button>
        </div>
      )}

      {crop && showTextOptions && (
        <div
          role="toolbar"
          className="an-subbar"
          onMouseDown={(event) => event.stopPropagation()}
        >
          <span className="an-sub-label">Text</span>
          <span className="an-sub-size" aria-hidden="true">
            A
          </span>
          <input
            type="range"
            aria-label="Text size"
            min={TEXT_MIN_SIZE}
            max={TEXT_MAX_SIZE}
            value={textSizeOn}
            onPointerDown={grabTextSize}
            onPointerUp={releaseTextSize}
            onPointerCancel={releaseTextSize}
            onChange={(event) => pickTextSize(Number(event.target.value))}
          />
          <span className="an-sub-size an-sub-size-big" aria-hidden="true">
            A
          </span>
          <span className="an-sub-value">{textSizeOn}</span>
          <span className="an-sep" />
          <button
            type="button"
            aria-label="Text background"
            title="Text background"
            className={textBgOn ? "an-tool an-active" : "an-tool"}
            onClick={toggleTextBg}
          >
            <ToolIcon tool="text-bg" />
          </button>
        </div>
      )}

      {textDraft && (
        <textarea
          ref={textRef}
          className={textBg ? "an-text-input an-text-solid" : "an-text-input"}
          style={{
            left: textBg ? textDraft.x - TEXT_BG_PAD_X : textDraft.x,
            top: textBg ? textDraft.y - TEXT_BG_PAD_Y : textDraft.y,
            font: textFont(textSize),
            lineHeight: TEXT_LINE,
            ...(editorCap !== null ? { maxWidth: editorCap } : {}),
            ...(textBg
              ? ({
                  background: color,
                  color: contrastInk(color),
                  caretColor: contrastInk(color),
                  padding: `${TEXT_BG_PAD_Y}px ${TEXT_BG_PAD_X}px`,
                  // Placeholder and selection read against this ink.
                  "--an-ph":
                    contrastInk(color) === "#ffffff"
                      ? "rgba(255, 255, 255, 0.55)"
                      : "rgba(28, 29, 34, 0.45)",
                } as React.CSSProperties)
              : {
                  color,
                  caretColor: color,
                  textShadow: "0 0 3px rgba(0,0,0,0.4)",
                }),
          }}
          rows={1}
          placeholder="Add text"
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
            // Width first: the height depends on how the text wraps.
            const el = event.currentTarget;
            el.style.width = "auto";
            el.style.width = `${Math.min(
              el.scrollWidth + 12,
              editorCap ?? window.innerWidth - textDraft.x - 10,
            )}px`;
            el.style.height = "auto";
            el.style.height = `${el.scrollHeight}px`;
          }}
        />
      )}
    </div>
  );
}
