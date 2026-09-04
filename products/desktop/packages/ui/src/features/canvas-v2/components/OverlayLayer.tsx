import {
  type BoardPaneRect,
  fragmentScreenRect,
  type ResizeHandle,
} from "@posthog/core/canvas-v2/boardGeometry";
import { TooltipProvider } from "@posthog/quill";
import type { CanvasV2Fragment, CanvasV2Viewport } from "@posthog/shared";
import {
  type FragmentLastEdit,
  FragmentOverlay,
} from "@posthog/ui/features/canvas-v2/components/FragmentOverlay";
import type { ReactElement } from "react";

interface OverlayLayerProps {
  fragments: CanvasV2Fragment[];
  viewport: CanvasV2Viewport;
  paneRect: BoardPaneRect;
  selectedIds: string[];
  highlightedIds: string[];
  fragmentErrors: Record<string, string>;
  lastEdits: Record<string, FragmentLastEdit>;
  onStartMove: (id: string, event: React.PointerEvent) => void;
  onStartResize: (
    id: string,
    handle: ResizeHandle,
    event: React.PointerEvent,
  ) => void;
  onEdit: (id: string) => void;
  onFocus: (id: string) => void;
  onDuplicate: (id: string) => void;
  onBringToFront: (id: string) => void;
  onDelete: (id: string) => void;
}

/**
 * The chrome above the board frame. The layer itself never takes a pointer
 * event, so a gesture on a fragment body still reaches the frame.
 */
export function OverlayLayer({
  fragments,
  viewport,
  paneRect,
  selectedIds,
  highlightedIds,
  fragmentErrors,
  lastEdits,
  onStartMove,
  onStartResize,
  onEdit,
  onFocus,
  onDuplicate,
  onBringToFront,
  onDelete,
}: OverlayLayerProps): ReactElement {
  const highlighted = new Set(highlightedIds);
  const selected = new Set(selectedIds);

  return (
    <TooltipProvider delay={400}>
      <div className="pointer-events-none absolute inset-0 z-10">
        {/* A hidden fragment draws nothing, so it gets no outline and no menu. */}
        {fragments
          .filter((fragment) => !fragment.hidden)
          .map((fragment) => {
            const screen = fragmentScreenRect(fragment, viewport, paneRect);
            const rect = {
              left: screen.left - paneRect.left,
              top: screen.top - paneRect.top,
              width: screen.width,
              height: screen.height,
            };
            return (
              <div
                key={fragment.id}
                className="pointer-events-none absolute inset-0"
                style={{ zIndex: fragment.z }}
              >
                <FragmentOverlay
                  fragment={fragment}
                  rect={rect}
                  selected={selected.has(fragment.id)}
                  resizable={
                    selectedIds.length === 1 && selected.has(fragment.id)
                  }
                  selectionCount={
                    selected.has(fragment.id) ? selectedIds.length : 1
                  }
                  highlighted={highlighted.has(fragment.id)}
                  error={fragmentErrors[fragment.id]}
                  lastEditedBy={lastEdits[fragment.id]}
                  onStartMove={(event) => onStartMove(fragment.id, event)}
                  onStartResize={(handle, event) =>
                    onStartResize(fragment.id, handle, event)
                  }
                  onEdit={() => onEdit(fragment.id)}
                  onFocus={() => onFocus(fragment.id)}
                  onDuplicate={() => onDuplicate(fragment.id)}
                  onBringToFront={() => onBringToFront(fragment.id)}
                  onDelete={() => onDelete(fragment.id)}
                />
              </div>
            );
          })}
      </div>
    </TooltipProvider>
  );
}
