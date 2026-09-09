import {
  getCellCount,
  getLayoutToFit,
  isBrainrotCell,
  isCanvasCell,
  isTerminalCell,
  type LayoutPreset,
  reflowCells,
} from "./grid";

export interface PlacementPlan {
  layout: LayoutPreset;
  cells: (string | null)[];
  /** Ids that landed in a tile, in the order they were given. */
  placed: string[];
  /** Ids with nowhere to go once the grid hit its ceiling. */
  overflow: string[];
  /** Ids already on the grid, left in the tile they were in. */
  alreadyPresent: string[];
}

export interface PlacementInput {
  cells: readonly (string | null)[];
  layout: LayoutPreset;
  taskIds: readonly string[];
  /**
   * The tasks that still exist. Cells are persisted and only pruned when a task
   * is archived, so a deleted task's id lingers in the array; the grid renders
   * that tile empty, and placement has to see the same free tile the user does.
   *
   * `null` when the task list isn't known yet, which holds every non-empty cell.
   * Guessing the other way would tile over sessions that are still on the grid.
   */
  liveTaskIds: ReadonlySet<string> | null;
}

/**
 * Where a batch of sessions should sit on the command center grid: empty tiles
 * first, in display order, growing the grid when the batch outgrows them.
 *
 * Occupied tiles are never overwritten, which also covers the brainrot and
 * terminal and canvas sentinels — they hold something the grid draws, so they
 * read as occupied like any cell holding a session.
 */
export function planCommandCenterPlacement(
  input: PlacementInput,
): PlacementPlan {
  const { layout, liveTaskIds, taskIds } = input;
  const batch = new Set(taskIds);
  // A cell is occupied when it holds something the grid actually draws. The
  // batch counts as live too, so a session already tiled is left where it is
  // rather than placed a second time.
  const isOccupied = (cell: string | null): cell is string =>
    cell != null &&
    (liveTaskIds == null ||
      isBrainrotCell(cell) ||
      isCanvasCell(cell) ||
      isTerminalCell(cell) ||
      liveTaskIds.has(cell) ||
      batch.has(cell));
  const occupants = new Set(input.cells.filter(isOccupied));

  const alreadyPresent: string[] = [];
  const queue: string[] = [];
  for (const id of batch) {
    if (occupants.has(id)) alreadyPresent.push(id);
    else queue.push(id);
  }

  if (queue.length === 0) {
    return {
      layout,
      cells: [...input.cells],
      placed: [],
      overflow: [],
      alreadyPresent,
    };
  }

  const nextLayout = getLayoutToFit(layout, occupants.size + queue.length);
  const cells =
    nextLayout === layout
      ? [...input.cells]
      : reflowCells(input.cells, layout, nextLayout);
  // reflowCells always sizes to the target, but the no-growth branch copies the
  // array as-is — and a persisted grid can be shorter than its own layout.
  while (cells.length < getCellCount(nextLayout)) cells.push(null);

  const placed: string[] = [];
  for (let i = 0; i < cells.length && queue.length > 0; i++) {
    if (isOccupied(cells[i])) continue;
    const id = queue.shift() as string;
    cells[i] = id;
    placed.push(id);
  }

  return { layout: nextLayout, cells, placed, overflow: queue, alreadyPresent };
}
