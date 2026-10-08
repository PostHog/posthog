import { libraryIcon } from "@posthog/ui/features/canvas/blocks/libraryCatalog";
import { useSourceDragStore } from "@posthog/ui/features/canvas/blocks/sourceDrag";
import { createPortal } from "react-dom";

const GHOST_OFFSET_X = 14;
const GHOST_OFFSET_Y = 10;

export function SourceDragOverlay() {
  const ghost = useSourceDragStore((state) => state.ghost);
  if (!ghost) return null;
  const Icon = libraryIcon(ghost.blockType);
  const x = ghost.x + GHOST_OFFSET_X;
  const y = ghost.y + GHOST_OFFSET_Y;
  return createPortal(
    <>
      {ghost.phase === "drag" ? (
        <div className="blocks-pointer-shield cursor-grabbing" />
      ) : null}
      <div
        className="blocks-drag-ghost"
        data-phase={ghost.phase}
        style={{
          transform: `translate3d(${x}px, ${y}px, 0) rotate(${ghost.tilt.toFixed(2)}deg)`,
        }}
      >
        <div className="blocks-drag-ghost-card flex w-[220px] items-center gap-2.5 rounded-lg border border-border bg-card px-3 py-2.5">
          <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-accent-3 text-accent-11">
            <Icon size={16} />
          </div>
          <div className="min-w-0">
            <div className="truncate font-medium text-[12.5px] text-foreground">
              {ghost.label}
            </div>
            <div className="truncate text-[11px] text-muted-foreground">
              {ghost.hint}
            </div>
          </div>
        </div>
      </div>
    </>,
    document.querySelector(".radix-themes") ?? document.body,
  );
}
