import {
  type BoardPaneRect,
  type BoardPoint,
  boardBounds,
} from "@posthog/core/canvas-v2/boardGeometry";
import type { CanvasV2Fragment, CanvasV2Viewport } from "@posthog/shared";
import { type ReactElement, useRef } from "react";

const MAP_WIDTH = 156;
const MAP_HEIGHT = 104;
const MAP_PADDING = 6;

interface BoardMinimapProps {
  fragments: readonly CanvasV2Fragment[];
  viewport: CanvasV2Viewport;
  paneRect: BoardPaneRect;
  selectedIds: readonly string[];
  /** Puts this world point at the middle of the pane. */
  onJump: (world: BoardPoint) => void;
}

/** The whole board at a glance, with the part you look at marked. */
export function BoardMinimap({
  fragments,
  viewport,
  paneRect,
  selectedIds,
  onJump,
}: BoardMinimapProps): ReactElement | null {
  const dragging = useRef(false);

  if (fragments.length === 0 || paneRect.width === 0) return null;

  const bounds = boardBounds(fragments);
  const inner = {
    w: MAP_WIDTH - MAP_PADDING * 2,
    h: MAP_HEIGHT - MAP_PADDING * 2,
  };
  const scale = Math.min(inner.w / bounds.w, inner.h / bounds.h);
  const offsetX = MAP_PADDING + (inner.w - bounds.w * scale) / 2;
  const offsetY = MAP_PADDING + (inner.h - bounds.h * scale) / 2;
  const toMap = (x: number, y: number): BoardPoint => ({
    x: offsetX + (x - bounds.x) * scale,
    y: offsetY + (y - bounds.y) * scale,
  });

  const viewOrigin = toMap(
    -viewport.x / viewport.zoom,
    -viewport.y / viewport.zoom,
  );
  const viewSize = {
    w: (paneRect.width / viewport.zoom) * scale,
    h: (paneRect.height / viewport.zoom) * scale,
  };
  const selected = new Set(selectedIds);
  // A press moves the view, and holding keeps moving it.
  const jump = (event: {
    clientX: number;
    clientY: number;
    currentTarget: Element;
  }): void => {
    const rect = event.currentTarget.getBoundingClientRect();
    onJump({
      x: bounds.x + (event.clientX - rect.left - offsetX) / scale,
      y: bounds.y + (event.clientY - rect.top - offsetY) / scale,
    });
  };

  return (
    <button
      type="button"
      aria-label="Jump to a place on the board"
      className="absolute right-4 bottom-4 z-40 cursor-pointer touch-none overflow-hidden rounded-(--radius-3) border border-(--gray-a5) bg-(--gray-1)/85 shadow-lg backdrop-blur-md transition-opacity hover:opacity-100"
      style={{ width: MAP_WIDTH, height: MAP_HEIGHT, opacity: 0.85 }}
      onPointerDown={(event) => {
        event.currentTarget.setPointerCapture(event.pointerId);
        dragging.current = true;
        jump(event);
      }}
      onPointerMove={(event) => {
        if (dragging.current) jump(event);
      }}
      onPointerUp={(event) => {
        dragging.current = false;
        event.currentTarget.releasePointerCapture(event.pointerId);
      }}
      onPointerCancel={() => {
        dragging.current = false;
      }}
    >
      {fragments
        .filter((fragment) => !fragment.hidden)
        .map((fragment) => {
          const point = toMap(fragment.x, fragment.y);
          return (
            <span
              key={fragment.id}
              className={`absolute rounded-[1.5px] ${
                selected.has(fragment.id) ? "bg-(--accent-9)" : "bg-(--gray-a7)"
              }`}
              style={{
                left: point.x,
                top: point.y,
                width: Math.max(2, fragment.w * scale),
                height: Math.max(2, fragment.h * scale),
              }}
            />
          );
        })}
      <span
        className="absolute rounded-[3px] border border-(--accent-a9) bg-(--accent-a2)"
        style={{
          left: viewOrigin.x,
          top: viewOrigin.y,
          width: viewSize.w,
          height: viewSize.h,
        }}
      />
    </button>
  );
}
