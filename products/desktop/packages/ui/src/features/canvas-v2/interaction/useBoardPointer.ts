import {
  BOARD_MIN_FRAGMENT_SIZE,
  type BoardPaneRect,
  type BoardPoint,
  type BoardRect,
  panBy,
  type ResizeHandle,
  resizeRect,
  screenToWorld,
  snapToGrid,
  zoomAround,
} from "@posthog/core/canvas-v2/boardGeometry";
import type {
  BoardFrameToHostMessage,
  CanvasV2Op,
  CanvasV2Snapshot,
  CanvasV2Viewport,
} from "@posthog/shared";
import { useCallback, useEffect, useRef, useState } from "react";

export type BoardGesture =
  | { kind: "none" }
  | { kind: "pan" }
  | { kind: "move"; id: string }
  | { kind: "resize"; id: string; handle: ResizeHandle };

export interface UseBoardPointerOptions {
  paneRef: React.RefObject<HTMLElement | null>;
  viewport: CanvasV2Viewport;
  setViewport: (v: CanvasV2Viewport) => void;
  getSnapshot: () => CanvasV2Snapshot;
  applyLocal: (ops: CanvasV2Op[]) => void;
  onSelect: (id: string | null) => void;
}

export interface BoardPointerHandle {
  gesture: BoardGesture;
  onFrameWheel(e: Extract<BoardFrameToHostMessage, { type: "wheel" }>): void;
  onFrameBackgroundPointer(
    e: Extract<BoardFrameToHostMessage, { type: "background-pointer" }>,
  ): void;
  onOverlayWheel(e: React.WheelEvent): void;
  startMove(id: string, e: React.PointerEvent): void;
  startResize(id: string, handle: ResizeHandle, e: React.PointerEvent): void;
}

/** A drag under this many screen px counts as a click, not a pan. */
const CLICK_SLOP_PX = 3;
/** Wheel delta that doubles the zoom. Chosen to feel like the other canvases. */
const ZOOM_WHEEL_SCALE = 300;
const PAN_BUTTONS = new Set([0, 1]);

interface DragState {
  pointerId: number;
  target: HTMLElement;
  start: BoardPoint;
  origin: BoardRect;
  sent: BoardRect;
}

interface PanState {
  last: BoardPoint;
  travel: number;
}

/**
 * The one place board gestures turn into viewport changes and fragment ops.
 * Frame messages and overlay pointer events meet here, so a drag that starts on
 * a title bar and a drag that starts on empty space follow the same rules.
 */
export function useBoardPointer(o: UseBoardPointerOptions): BoardPointerHandle {
  const latest = useRef(o);
  latest.current = o;

  const [gesture, setGesture] = useState<BoardGesture>({ kind: "none" });
  const drag = useRef<DragState | null>(null);
  const pan = useRef<PanState | null>(null);

  const readPane = useCallback(
    (): BoardPaneRect => readPaneRect(latest.current.paneRef.current),
    [],
  );

  const zoomOrPan = useCallback(
    (e: {
      deltaX: number;
      deltaY: number;
      ctrlKey: boolean;
      metaKey: boolean;
      clientX: number;
      clientY: number;
    }): void => {
      const { viewport, setViewport } = latest.current;
      if (e.ctrlKey || e.metaKey) {
        const factor = Math.exp(-e.deltaY / ZOOM_WHEEL_SCALE);
        setViewport(
          zoomAround(
            viewport,
            { x: e.clientX, y: e.clientY },
            factor,
            readPane(),
          ),
        );
        return;
      }
      setViewport(panBy(viewport, -e.deltaX, -e.deltaY));
    },
    [readPane],
  );

  // Frame points are relative to the iframe, which fills the pane.
  const onFrameWheel = useCallback(
    (e: Extract<BoardFrameToHostMessage, { type: "wheel" }>): void => {
      const pane = readPane();
      zoomOrPan({
        deltaX: e.deltaX,
        deltaY: e.deltaY,
        ctrlKey: e.ctrlKey,
        metaKey: e.metaKey,
        clientX: e.clientX + pane.left,
        clientY: e.clientY + pane.top,
      });
    },
    [readPane, zoomOrPan],
  );

  const onOverlayWheel = useCallback(
    (e: React.WheelEvent): void => {
      zoomOrPan({
        deltaX: e.deltaX,
        deltaY: e.deltaY,
        ctrlKey: e.ctrlKey,
        metaKey: e.metaKey,
        clientX: e.clientX,
        clientY: e.clientY,
      });
    },
    [zoomOrPan],
  );

  const onFrameBackgroundPointer = useCallback(
    (
      e: Extract<BoardFrameToHostMessage, { type: "background-pointer" }>,
    ): void => {
      const pane = readPane();
      const point = { x: e.clientX + pane.left, y: e.clientY + pane.top };

      if (e.phase === "down") {
        if (!PAN_BUTTONS.has(e.button)) return;
        pan.current = { last: point, travel: 0 };
        setGesture({ kind: "pan" });
        return;
      }

      const active = pan.current;
      if (!active) return;

      const dx = point.x - active.last.x;
      const dy = point.y - active.last.y;

      if (e.phase === "move") {
        active.last = point;
        active.travel += Math.abs(dx) + Math.abs(dy);
        const { viewport, setViewport } = latest.current;
        setViewport(panBy(viewport, dx, dy));
        return;
      }

      if (active.travel <= CLICK_SLOP_PX) latest.current.onSelect(null);
      pan.current = null;
      setGesture({ kind: "none" });
    },
    [readPane],
  );

  // A release that the frame never relays, because the pointer left the window,
  // must not leave the board in a pan for ever.
  useEffect(() => {
    const end = (): void => {
      if (!pan.current) return;
      pan.current = null;
      setGesture({ kind: "none" });
    };
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
    window.addEventListener("blur", end);
    return () => {
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
      window.removeEventListener("blur", end);
    };
  }, []);

  const startDrag = useCallback(
    (id: string, e: React.PointerEvent, next: BoardGesture): void => {
      const fragment = latest.current
        .getSnapshot()
        .fragments.find((candidate) => candidate.id === id);
      if (!fragment) return;

      const target = e.currentTarget as HTMLElement;
      e.preventDefault();
      e.stopPropagation();
      target.setPointerCapture(e.pointerId);

      const origin: BoardRect = {
        x: fragment.x,
        y: fragment.y,
        w: fragment.w,
        h: fragment.h,
      };
      drag.current = {
        pointerId: e.pointerId,
        target,
        start: { x: e.clientX, y: e.clientY },
        origin,
        sent: origin,
      };
      setGesture(next);
      latest.current.onSelect(id);
    },
    [],
  );

  const startMove = useCallback(
    (id: string, e: React.PointerEvent): void => {
      startDrag(id, e, { kind: "move", id });
    },
    [startDrag],
  );

  const startResize = useCallback(
    (id: string, handle: ResizeHandle, e: React.PointerEvent): void => {
      startDrag(id, e, { kind: "resize", id, handle });
    },
    [startDrag],
  );

  useEffect(() => {
    const active = gesture;
    if (active.kind !== "move" && active.kind !== "resize") return;

    const onPointerMove = (event: PointerEvent): void => {
      const state = drag.current;
      if (!state || state.pointerId !== event.pointerId) return;

      const { viewport, applyLocal } = latest.current;
      const dx = (event.clientX - state.start.x) / viewport.zoom;
      const dy = (event.clientY - state.start.y) / viewport.zoom;
      const next =
        active.kind === "move"
          ? { ...state.origin, x: state.origin.x + dx, y: state.origin.y + dy }
          : resizeRect(
              state.origin,
              active.handle,
              dx,
              dy,
              BOARD_MIN_FRAGMENT_SIZE,
            );
      const snapped: BoardRect = {
        x: snapToGrid(next.x),
        y: snapToGrid(next.y),
        w: snapToGrid(next.w),
        h: snapToGrid(next.h),
      };
      if (sameRect(snapped, state.sent)) return;
      state.sent = snapped;

      applyLocal([
        {
          type: "update_fragment",
          id: active.id,
          patch:
            active.kind === "move"
              ? { x: snapped.x, y: snapped.y }
              : { x: snapped.x, y: snapped.y, w: snapped.w, h: snapped.h },
        },
      ]);
    };

    const onPointerUp = (event: PointerEvent): void => {
      const state = drag.current;
      if (state && state.pointerId === event.pointerId) {
        // A pointerup releases capture on its own; a cancel may not.
        if (state.target.hasPointerCapture(event.pointerId)) {
          state.target.releasePointerCapture(event.pointerId);
        }
        drag.current = null;
      }
      setGesture({ kind: "none" });
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerUp);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointercancel", onPointerUp);
    };
  }, [gesture]);

  return {
    gesture,
    onFrameWheel,
    onFrameBackgroundPointer,
    onOverlayWheel,
    startMove,
    startResize,
  };
}

/** The pane in client coordinates, or a zero rect before the pane mounts. */
export function readPaneRect(element: HTMLElement | null): BoardPaneRect {
  if (!element) return { left: 0, top: 0, width: 0, height: 0 };
  const rect = element.getBoundingClientRect();
  return {
    left: rect.left,
    top: rect.top,
    width: rect.width,
    height: rect.height,
  };
}

/** Where a client point lands on the board. */
export function clientToWorld(
  point: BoardPoint,
  viewport: CanvasV2Viewport,
  element: HTMLElement | null,
): BoardPoint {
  return screenToWorld(point, viewport, readPaneRect(element));
}

function sameRect(a: BoardRect, b: BoardRect): boolean {
  return a.x === b.x && a.y === b.y && a.w === b.w && a.h === b.h;
}
