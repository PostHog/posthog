import { Button } from "@posthog/quill";
import { destroyShellTerminal } from "@posthog/ui/features/terminal/destroyShellTerminal";
import { useCallback, useEffect, useRef, useState } from "react";
import { FOCUSABLE_SELECTOR } from "../../../utils/overlay";
import {
  getGridDimensions,
  type LayoutPreset,
  useCommandCenterStore,
} from "../commandCenterStore";
import type { CommandCenterCellData } from "../hooks/useCommandCenterData";
import { getTerminalCellStateKey } from "../terminalCells";
import { CommandCenterPanel } from "./CommandCenterPanel";

interface CommandCenterGridProps {
  layout: LayoutPreset;
  cells: CommandCenterCellData[];
}

function useTaskDragActive() {
  const [active, setActive] = useState(false);

  useEffect(() => {
    const onDragStart = (e: DragEvent) => {
      if (e.dataTransfer?.types.includes("text/x-task-id")) {
        setActive(true);
      }
    };
    const onDragEnd = () => setActive(false);
    const onDrop = () => setActive(false);
    const onDragLeave = (e: DragEvent) => {
      if (!e.relatedTarget) setActive(false);
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

function GridCell({
  cell,
  zoom,
  isDragActive,
  isActive,
  pendingPlacement,
}: {
  cell: CommandCenterCellData;
  zoom: number;
  isDragActive: boolean;
  isActive: boolean;
  pendingPlacement: { taskId: string; taskTitle: string } | null;
}) {
  const cellRef = useRef<HTMLDivElement>(null);
  const [isDragOver, setIsDragOver] = useState(false);
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

  const handleDragOver = useCallback((e: React.DragEvent) => {
    if (e.dataTransfer.types.includes("text/x-task-id")) {
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
      setIsDragOver(true);
    }
  }, []);

  const handleDragLeave = useCallback(() => {
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      const taskId = e.dataTransfer.getData("text/x-task-id");
      if (taskId) {
        if (cell.terminalId) {
          destroyShellTerminal(getTerminalCellStateKey(cell.terminalId));
        }
        useCommandCenterStore.getState().assignTask(cell.cellIndex, taskId);
      }
    },
    [cell.cellIndex, cell.terminalId],
  );

  const handleReplacement = useCallback(() => {
    if (!pendingPlacement) return;
    if (cell.terminalId) {
      destroyShellTerminal(getTerminalCellStateKey(cell.terminalId));
    }
    useCommandCenterStore
      .getState()
      .assignTask(cell.cellIndex, pendingPlacement.taskId);
  }, [cell.cellIndex, cell.terminalId, pendingPlacement]);

  const replacementLabel = cell.terminalId
    ? "Replace terminal"
    : cell.isBrainrot
      ? "Replace Brainrot"
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
        className="h-full w-full origin-top-left"
        style={{
          zoom: zoom !== 1 ? zoom : undefined,
        }}
      >
        <CommandCenterPanel cell={cell} isActiveSession={isActive} />
      </div>
      {isActive && (
        <div className="pointer-events-none absolute inset-0 border-2 border-accent-9" />
      )}
      {isDragActive && (
        // biome-ignore lint/a11y/noStaticElementInteractions: transparent overlay to capture drag events over session content
        <div
          className="absolute inset-0"
          style={{
            outline: isDragOver ? "2px solid var(--accent-9)" : undefined,
            outlineOffset: "-2px",
          }}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        />
      )}
      {pendingPlacement && (
        <button
          type="button"
          className="absolute inset-0 z-10 flex cursor-pointer items-center justify-center bg-gray-12/60 p-4 text-center font-medium text-sm text-white transition-colors hover:bg-accent-9/80 focus-visible:bg-accent-9/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-7 focus-visible:ring-inset"
          onClick={handleReplacement}
          aria-label={`${replacementLabel} with ${pendingPlacement.taskTitle}`}
        >
          {replacementLabel}
        </button>
      )}
    </div>
  );
}

export function CommandCenterGrid({ layout, cells }: CommandCenterGridProps) {
  const { cols, rows } = getGridDimensions(layout);
  const zoom = useCommandCenterStore((s) => s.zoom);
  const activeCellIndex = useCommandCenterStore((s) => s.activeCellIndex);
  const isDragActive = useTaskDragActive();
  const pendingPlacement = useCommandCenterStore((s) => s.pendingPlacement);
  const cancelPlacement = useCommandCenterStore((s) => s.cancelPlacement);

  useEffect(() => {
    if (!pendingPlacement) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") cancelPlacement();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [cancelPlacement, pendingPlacement]);

  return (
    <div className="relative h-full">
      {pendingPlacement && (
        <div className="-translate-x-1/2 absolute top-3 left-1/2 z-20 flex items-center gap-3 rounded-md border border-gray-7 bg-gray-1 px-3 py-2 shadow-lg">
          <span className="whitespace-nowrap text-sm">
            Choose a tile for {pendingPlacement.taskTitle}
          </span>
          <Button variant="outline" size="xs" onClick={cancelPlacement}>
            Cancel
          </Button>
        </div>
      )}
      <div
        className="grid h-full gap-[1px] bg-gray-6"
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
            isDragActive={isDragActive}
            isActive={activeCellIndex === cell.cellIndex}
            pendingPlacement={pendingPlacement}
          />
        ))}
      </div>
    </div>
  );
}
