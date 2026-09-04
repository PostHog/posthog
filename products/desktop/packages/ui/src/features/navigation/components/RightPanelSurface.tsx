import {
  type PanelGeometry,
  PUSH_MAX_CSS,
  ROW_CEILING_CSS,
} from "@posthog/ui/features/navigation/rightPanelGeometry";
import type { ReactNode, RefObject } from "react";

/** How long the panel takes to slide in, widen, or go away. */
export const SLIDE_MS = 200;

/**
 * The panel's two layers. The spacer pushes the pane over and stops at its share
 * of the row; the panel is laid over the row's right edge at whatever width it
 * has, so past that point it widens across a pane that no longer reflows.
 * Expanding is then a wider panel over a parked pane, not a relayout.
 *
 * Both belong to the content row, which is what keeps the nav uncovered.
 */
export function RightPanelSurface({
  panelRef,
  open,
  expanded,
  width,
  geometry,
  isResizing,
  onUncover,
  children,
}: {
  panelRef: RefObject<HTMLDivElement | null>;
  open: boolean;
  /** Taking the whole row, rather than the width it was dragged to. */
  expanded: boolean;
  width: number;
  geometry: PanelGeometry;
  isResizing: boolean;
  /** The reader clicked the covered pane, asking for it back. */
  onUncover?: () => void;
  children?: ReactNode;
}) {
  // A drag has to keep up with the pointer frame for frame, not ease toward it.
  const slide = isResizing ? "0ms" : `${SLIDE_MS}ms`;

  return (
    <>
      {/* Stops at the panel's push share; past that the pane holds still. */}
      <div
        className="h-full shrink-0 transition-[width] ease-out motion-reduce:transition-none"
        style={{
          width: open ? `min(${width}px, ${PUSH_MAX_CSS})` : "0px",
          transitionDuration: slide,
        }}
      />
      {/* A covered pane is a remnant, not somewhere to work, so it steps back;
          clicking it asks for the pane back. Out of the tab order - the header's
          own button goes to the same place. */}
      <button
        type="button"
        aria-hidden
        tabIndex={-1}
        onClick={() => onUncover?.()}
        className="absolute inset-0 z-30 cursor-default border-0 bg-[rgba(0,0,0,0.2)] p-0 transition-opacity duration-200 ease-out motion-reduce:transition-none"
        style={{
          opacity: geometry.covering ? 1 : 0,
          pointerEvents: geometry.covering ? "auto" : "none",
        }}
      />
      <div
        ref={panelRef}
        className="absolute inset-y-0 right-0 z-40 flex min-w-0 flex-col border-gray-6 border-l bg-background transition-[width,transform] ease-out motion-reduce:transition-none"
        style={{
          width: expanded ? "100%" : `${width}px`,
          // One ceiling for both widths, so a width stored on a wider window
          // lands where expanding would.
          maxWidth: ROW_CEILING_CSS,
          transform: open ? "translateX(0)" : "translateX(100%)",
          pointerEvents: open ? undefined : "none",
          transitionDuration: slide,
        }}
      >
        {children}
      </div>
    </>
  );
}
