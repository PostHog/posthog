import type { CanvasLayout, LayoutOperation } from "./gridLayoutSchemas";

/**
 * A layout document with the server's own operations applied to it. The server
 * stays the authority — it validates geometry and overlaps and mints the next
 * version — so this exists for what a surface shows while its patch is in
 * flight, and has to stay a pure function of the document it is handed.
 */
export function applyLayoutOperations(
  layout: CanvasLayout,
  operations: LayoutOperation[],
): CanvasLayout {
  return operations.reduce(applyOperation, layout);
}

function applyOperation(
  layout: CanvasLayout,
  operation: LayoutOperation,
): CanvasLayout {
  switch (operation.op) {
    case "set_grid":
      return { ...layout, grid: operation.grid };
    case "add_placement":
      return {
        ...layout,
        placements: [...layout.placements, operation.placement],
      };
    case "update_placement":
      return {
        ...layout,
        placements: layout.placements.map((placement) =>
          placement.id === operation.id
            ? { ...placement, ...operation.changes }
            : placement,
        ),
      };
    case "remove_placement":
      return {
        ...layout,
        placements: layout.placements.filter(
          (placement) => placement.id !== operation.id,
        ),
      };
  }
}
