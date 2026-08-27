import { Plus } from "@phosphor-icons/react";
import {
  type ExpandDirection,
  getExpandedLayout,
  getExpansionCellIndex,
} from "@posthog/core/command-center/grid";
import { Button } from "@posthog/quill";
import {
  CANVAS_DRAG_TYPE,
  readCanvasDragData,
} from "@posthog/ui/features/canvas/canvasDrag";
import {
  consumeTaskDrop,
  readTaskDragData,
  TASK_DRAG_TYPE,
  TASK_IDS_DRAG_TYPE,
} from "@posthog/ui/features/sidebar/taskDrag";
import { useLiveTaskIds } from "@posthog/ui/features/tasks/useLiveTaskIds";
import { destroyShellTerminal } from "@posthog/ui/features/terminal/destroyShellTerminal";
import { useCallback, useEffect, useRef, useState } from "react";
import { FOCUSABLE_SELECTOR } from "../../../utils/overlay";
import {
  type CommandCenterPlacement,
  getGridDimensions,
  type LayoutPreset,
  useCommandCenterStore,
} from "../commandCenterStore";
import type { CommandCenterCellData } from "../hooks/useCommandCenterData";
import {
  expandCanvasInCommandCenterInto,
  expandTasksInCommandCenterInto,
  placeCanvasInCommandCenterCell,
  placeTasksInCommandCenterCell,
} from "../placeTaskInCommandCenter";
import { getTerminalCellStateKey } from "../terminalCells";
import { CommandCenterPanel } from "./CommandCenterPanel";

/**
 * Picking a tile by clicking and by dropping are the same interaction, so they
 * render the same targets: every tile plus the expand zones. Only how the task
 * arrives differs — a click carries the task the picker was opened with, a drop
 * carries whatever was dragged.
 */
type PlacementState =
  | ({ mode: "pick" } & CommandCenterPlacement)
  | { mode: "drag"; kind: CommandCenterPlacement["kind"] };

type DroppedItem =
  | { kind: "task"; ids: string[] }
  | { kind: "canvas"; id: string };

interface CommandCenterGridProps {
  layout: LayoutPreset;
  cells: CommandCenterCellData[];
}

function draggedItemKind(
  types: readonly string[],
): CommandCenterPlacement["kind"] | null {
  if (types.includes(CANVAS_DRAG_TYPE)) return "canvas";
  if (types.includes(TASK_IDS_DRAG_TYPE) || types.includes(TASK_DRAG_TYPE)) {
    return "task";
  }
  return null;
}

function useCellDragActive() {
  const [active, setActive] = useState<CommandCenterPlacement["kind"] | null>(
    null,
  );

  useEffect(() => {
    const onDragStart = (e: DragEvent) => {
      if (e.dataTransfer) {
        setActive(draggedItemKind(e.dataTransfer.types));
      }
    };
    const onDragEnd = () => setActive(null);
    const onDrop = () => setActive(null);
    const onDragLeave = (e: DragEvent) => {
      if (!e.relatedTarget) setActive(null);
    };

    document.addEventListener("dragstart", onDragStart);
    document.addEventListener("dragend", onDragEnd);
    document.addEventListener("drop", onDrop);
    document.addEventListener("dragleave", onDragLeave);
    return () => {
      document.removeEventListener("dragstart", onDragStart);
      document.removeEventListener("dragend", onDragEnd);
      document.removeEventListener("drop", onDrop);
      document.removeEventListener("dragleave", onDragLeave);
    };
  }, []);

  return active;
}

function useCellDropTarget(onItem: (item: DroppedItem) => void) {
  const [isOver, setIsOver] = useState(false);

  return {
    isOver,
    onDragOver: (e: React.DragEvent) => {
      if (!draggedItemKind(e.dataTransfer.types)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
      setIsOver(true);
    },
    onDragLeave: () => setIsOver(false),
    onDrop: (e: React.DragEvent) => {
      e.preventDefault();
      setIsOver(false);
      const canvasId = readCanvasDragData(e.dataTransfer);
      if (canvasId) {
        onItem({ kind: "canvas", id: canvasId });
        return;
      }
      const taskIds = readTaskDragData(e.dataTransfer);
      if (taskIds.length === 0) return;
      // Filing is what this drop was for, so the pin drag behind the same
      // gesture leaves the sessions pinned where they were.
      consumeTaskDrop();
      onItem({ kind: "task", ids: taskIds });
    },
  };
}

const TARGET_CLASSES =
  "group flex cursor-pointer items-center justify-center transition-colors focus-visible:outline-none";

// Targets are outlined, never dimmed: a scrim over every tile buries the grid
// you're picking from, and its label had to fight the tile behind it.
function targetOutline(isOver: boolean): string {
  return isOver
    ? "ring-2 ring-accent-9 ring-inset"
    : "ring-1 ring-gray-7 ring-inset hover:ring-2 hover:ring-accent-9 focus-visible:ring-2 focus-visible:ring-accent-9";
}

/** Shown only on the target under the cursor, so the grid stays legible. */
function hoverTextTone(isOver: boolean): string {
  return isOver
    ? "opacity-100"
    : "opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100";
}

function TargetLabel({
  isOver,
  children,
}: {
  isOver: boolean;
  children: React.ReactNode;
}) {
  return (
    <span
      className={`flex items-center gap-1.5 rounded-md bg-accent-9 px-2 py-1 text-center font-medium text-[11px] text-white shadow-sm transition-opacity ${hoverTextTone(isOver)}`}
    >
      {children}
    </span>
  );
}

function GridCell({
  cell,
  zoom,
  isActive,
  placement,
}: {
  cell: CommandCenterCellData;
  zoom: number;
  isActive: boolean;
  placement: PlacementState | null;
}) {
  const cellRef = useRef<HTMLDivElement>(null);
  const setActiveTask = useCommandCenterStore((s) => s.setActiveTask);
  const setActiveCell = useCommandCenterStore((s) => s.setActiveCell);

  const markActive = useCallback(() => {
    setActiveCell(cell.cellIndex);
    setActiveTask(cell.taskId);
  }, [cell.cellIndex, cell.taskId, setActiveCell, setActiveTask]);

  const handleCellClick = useCallback(
    (e: React.MouseEvent) => {
      markActive();
      const target = e.target as HTMLElement;
      // Don't redirect focus when the click already lands on a real control,
      // or when it bubbled in from a portaled popover whose DOM target is
      // outside this cell. Either way the click is targeting something that
      // owns its own focus.
      if (
        !e.currentTarget.contains(target) ||
        target.closest(FOCUSABLE_SELECTOR)
      ) {
        return;
      }
      const selection = window.getSelection();
      if (selection && !selection.isCollapsed) return;
      cellRef.current
        ?.querySelector<HTMLElement>("[tabindex='0']")
        ?.focus({ preventScroll: true });
    },
    [markActive],
  );

  const liveTaskIds = useLiveTaskIds();
  const placeInCell = useCallback(
    (item: DroppedItem) => {
      if (cell.terminalId) {
        destroyShellTerminal(getTerminalCellStateKey(cell.terminalId));
      }
      if (item.kind === "canvas") {
        placeCanvasInCommandCenterCell(item.id, cell.cellIndex);
      } else {
        placeTasksInCommandCenterCell(item.ids, cell.cellIndex, liveTaskIds);
      }
    },
    [cell.cellIndex, cell.terminalId, liveTaskIds],
  );

  const dropTarget = useCellDropTarget(placeInCell);

  const isEmpty =
    !cell.task && !cell.canvasId && !cell.terminalId && !cell.isBrainrot;

  const targetLabel = cell.terminalId
    ? "Replace terminal"
    : cell.isBrainrot
      ? "Replace Brainrot"
      : cell.canvasId
        ? "Replace canvas"
        : cell.task?.title
          ? `Replace ${cell.task.title}`
          : "Use this tile";

  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents lint/a11y/noStaticElementInteractions: click delegates focus to ActionSelector within
    <div
      ref={cellRef}
      data-grid-cell
      className="relative overflow-hidden bg-gray-1"
      onClick={handleCellClick}
      onPointerDownCapture={markActive}
      onFocusCapture={markActive}
    >
      <div
        // An empty tile's "Add task" prompt would sit right under the target
        // label, so it steps aside while a placement is in flight.
        className={`h-full w-full origin-top-left ${placement && isEmpty ? "invisible" : ""}`}
        style={{
          zoom: zoom !== 1 ? zoom : undefined,
        }}
      >
        <CommandCenterPanel cell={cell} isActiveSession={isActive} />
      </div>
      {isActive && (
        <div className="pointer-events-none absolute inset-0 border-2 border-accent-9" />
      )}
      {placement && (
        <button
          type="button"
          className={`absolute inset-0 z-10 p-4 ${TARGET_CLASSES} ${targetOutline(dropTarget.isOver)}`}
          onClick={
            placement.mode === "pick"
              ? () =>
                  placeInCell(
                    placement.kind === "canvas"
                      ? { kind: "canvas", id: placement.id }
                      : { kind: "task", ids: [placement.id] },
                  )
              : undefined
          }
          onDragOver={dropTarget.onDragOver}
          onDragLeave={dropTarget.onDragLeave}
          onDrop={dropTarget.onDrop}
          aria-label={
            placement.mode === "pick"
              ? `${targetLabel} with ${placement.title}`
              : targetLabel
          }
        >
          <TargetLabel isOver={dropTarget.isOver}>{targetLabel}</TargetLabel>
        </button>
      )}
    </div>
  );
}

function ExpandSlot({
  direction,
  expanded,
  slot,
  placement,
}: {
  direction: ExpandDirection;
  expanded: LayoutPreset;
  slot: number;
  placement: PlacementState;
}) {
  const liveTaskIds = useLiveTaskIds();
  const expand = useCallback(
    (item: DroppedItem) => {
      if (item.kind === "canvas") {
        expandCanvasInCommandCenterInto(direction, slot, item.id);
      } else {
        expandTasksInCommandCenterInto(direction, slot, item.ids, liveTaskIds);
      }
    },
    [direction, liveTaskIds, slot],
  );
  const dropTarget = useCellDropTarget(expand);
  const { cols, rows } = getGridDimensions(expanded);

  return (
    <button
      type="button"
      className={`flex-1 p-1 text-accent-11 ${TARGET_CLASSES} ${targetOutline(dropTarget.isOver)}`}
      onClick={
        placement.mode === "pick"
          ? () =>
              expand(
                placement.kind === "canvas"
                  ? { kind: "canvas", id: placement.id }
                  : { kind: "task", ids: [placement.id] },
              )
          : undefined
      }
      onDragOver={dropTarget.onDragOver}
      onDragLeave={dropTarget.onDragLeave}
      onDrop={dropTarget.onDrop}
      aria-label={
        direction === "horizontal"
          ? `Expand into a new column, row ${slot + 1} of ${rows}`
          : `Expand into a new row, column ${slot + 1} of ${cols}`
      }
    >
      <span className="flex flex-col items-center gap-1">
        <Plus size={14} weight="bold" />
        <span
          className={`text-[10px] leading-tight transition-opacity ${hoverTextTone(dropTarget.isOver)}`}
        >
          Expand into this tile
        </span>
      </span>
    </button>
  );
}

/**
 * The column or row an expansion would add, drawn as one target per tile so the
 * pick says which new tile the task goes in.
 */
function ExpandStrip({
  direction,
  layout,
  placement,
}: {
  direction: ExpandDirection;
  layout: LayoutPreset;
  placement: PlacementState;
}) {
  const expanded = getExpandedLayout(layout, direction);
  if (!expanded) return null;

  const { cols, rows } = getGridDimensions(layout);
  const isHorizontal = direction === "horizontal";
  // One target per new tile, keyed by the cell each would fill.
  const slotCells = Array.from({ length: isHorizontal ? rows : cols }, (_, i) =>
    getExpansionCellIndex(expanded, direction, i),
  );

  return (
    <div
      className={`flex shrink-0 gap-px bg-gray-2 ${
        isHorizontal ? "w-14 flex-col" : "h-14"
      }`}
    >
      {slotCells.map((cellIndex, slot) => (
        <ExpandSlot
          key={cellIndex}
          direction={direction}
          expanded={expanded}
          slot={slot}
          placement={placement}
        />
      ))}
    </div>
  );
}

export function CommandCenterGrid({ layout, cells }: CommandCenterGridProps) {
  const { cols, rows } = getGridDimensions(layout);
  const zoom = useCommandCenterStore((s) => s.zoom);
  const activeCellIndex = useCommandCenterStore((s) => s.activeCellIndex);
  const draggedKind = useCellDragActive();
  const pendingPlacement = useCommandCenterStore((s) => s.pendingPlacement);
  const cancelPlacement = useCommandCenterStore((s) => s.cancelPlacement);

  const placement: PlacementState | null = pendingPlacement
    ? { mode: "pick", ...pendingPlacement }
    : draggedKind
      ? { mode: "drag", kind: draggedKind }
      : null;

  useEffect(() => {
    if (!pendingPlacement) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") cancelPlacement();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [cancelPlacement, pendingPlacement]);

  return (
    <div className="relative flex h-full flex-col">
      {pendingPlacement && (
        // Accent-tinted so the bar reads as a mode you're in, not a panel
        // floating over the grid.
        <div className="-translate-x-1/2 absolute top-3 left-1/2 z-20 flex items-center gap-3 rounded-full border border-accent-7 bg-accent-3 px-3 py-1.5 shadow-md">
          <span className="whitespace-nowrap text-[12px] text-accent-12">
            Choose a tile for {pendingPlacement.title}
          </span>
          <Button variant="link-muted" size="xs" onClick={cancelPlacement}>
            Cancel
          </Button>
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
          <div
            className="grid min-h-0 flex-1 gap-[1px] bg-gray-6"
            style={{
              gridTemplateColumns: `repeat(${cols}, 1fr)`,
              gridTemplateRows: `repeat(${rows}, 1fr)`,
            }}
          >
            {cells.map((cell) => (
              <GridCell
                key={cell.cellIndex}
                cell={cell}
                zoom={zoom}
                isActive={activeCellIndex === cell.cellIndex}
                placement={placement}
              />
            ))}
          </div>
          {placement && (
            <ExpandStrip
              direction="vertical"
              layout={layout}
              placement={placement}
            />
          )}
        </div>
        {placement && (
          <ExpandStrip
            direction="horizontal"
            layout={layout}
            placement={placement}
          />
        )}
      </div>
    </div>
  );
}
