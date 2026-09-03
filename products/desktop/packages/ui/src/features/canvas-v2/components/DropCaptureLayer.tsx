import type { BoardPoint } from "@posthog/core/canvas-v2/boardGeometry";
import type { ReactElement } from "react";

/** The drag payload the library palette writes and the board reads. */
export const CANVAS_V2_DRAG_MIME = "application/x-posthog-canvas-v2-fragment";

interface DropCaptureLayerProps {
  /** Mounted only while a palette drag runs, so it never eats other clicks. */
  active: boolean;
  toWorld: (client: BoardPoint) => BoardPoint;
  onDropFragment: (name: string, world: BoardPoint) => void;
}

/**
 * Catches palette drops above the board frame. Without it the drop lands in the
 * sandboxed iframe document, where the host cannot see it.
 */
export function DropCaptureLayer({
  active,
  toWorld,
  onDropFragment,
}: DropCaptureLayerProps): ReactElement | null {
  if (!active) return null;

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: a drop target for a mouse drag, not a control; the palette also adds a fragment on click
    <div
      className="absolute inset-0 z-20"
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
      }}
      onDrop={(event) => {
        event.preventDefault();
        const name = event.dataTransfer.getData(CANVAS_V2_DRAG_MIME);
        if (!name) return;
        onDropFragment(name, toWorld({ x: event.clientX, y: event.clientY }));
      }}
    />
  );
}
