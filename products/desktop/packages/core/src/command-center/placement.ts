import {
  getCellCount,
  getLayoutToFit,
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
}

/**
 * Where a batch of sessions should sit on the command center grid: empty tiles
 * first, in display order, growing the grid when the batch outgrows them.
 *
 * Occupied tiles are never overwritten, which also covers the brainrot and
 * terminal sentinels — they read as occupied like any other non-empty cell.
 */
export function planCommandCenterPlacement(
  input: PlacementInput,
): PlacementPlan {
  const { layout, taskIds } = input;
  const occupants = new Set(
    input.cells.filter((cell): cell is string => cell != null),
  );

  const alreadyPresent: string[] = [];
  const queue: string[] = [];
  for (const id of new Set(taskIds)) {
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
    if (cells[i] != null) continue;
    const id = queue.shift() as string;
    cells[i] = id;
    placed.push(id);
  }

  return { layout: nextLayout, cells, placed, overflow: queue, alreadyPresent };
}
