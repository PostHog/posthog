import { cn, MenuLabel } from "@posthog/quill";
import type { ReactNode, RefObject } from "react";

/**
 * The pinned run at the top of a session list, doubling as the box that decides
 * pin from unpin. Always rendered, empty or not: inserting it on dragstart
 * restructures the list under the dragged row, and Chromium ends the drag on
 * the spot. It opens with a transition instead.
 */
export function PinnedRun({
  dropRef,
  dragging,
  highlight,
  hasItems,
  children,
}: {
  dropRef: RefObject<HTMLDivElement | null>;
  dragging: boolean;
  /** The run is the drop target under the pointer, and the drag came from outside it. */
  highlight: boolean;
  hasItems: boolean;
  children: ReactNode;
}) {
  return (
    <div
      ref={dropRef}
      className={cn(
        // `min-h-0` is the resting end of the transition. min-height starts at
        // `auto`, which is not interpolable, so without it the run snaps open.
        "flex min-h-0 flex-col gap-px rounded-md transition-[min-height,background-color] duration-150 ease-out motion-reduce:transition-none",
        // A floor, not a height, so a taller run keeps its own.
        dragging && "min-h-[100px]",
        highlight && "bg-accent-2 ring-1 ring-accent-6",
      )}
    >
      {/* Grid rows, so the label keeps its own height while the run opens. */}
      <div
        className={cn(
          "grid transition-[grid-template-rows] duration-150 ease-out motion-reduce:transition-none",
          hasItems || dragging ? "grid-rows-[1fr]" : "grid-rows-[0fr]",
        )}
      >
        <div className="overflow-hidden">
          <MenuLabel>Pinned</MenuLabel>
        </div>
      </div>
      {children}
    </div>
  );
}
