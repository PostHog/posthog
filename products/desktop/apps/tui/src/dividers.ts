import { type LayoutNode, splitSizes } from "./layout";

// A split draws one line between neighbours: left of each column after the first, above each row after the first.
export type Divider = "left" | "top" | null;

// Where a layout node sits in the chat area, counting its own divider.
export interface Cell {
  node: LayoutNode;
  divider: Divider;
  x: number;
  y: number;
  width: number;
  height: number;
}

// A split's children with whole-cell sizes; flex layout rounds half cells and leaves gaps.
export function splitCells(cell: Cell): Cell[] {
  const { node, divider } = cell;
  if (node.kind !== "split") return [];
  const across = node.direction === "row";
  // The split's own divider takes a row or column before its children share the rest.
  const x = cell.x + (divider === "left" ? 1 : 0);
  const y = cell.y + (divider === "top" ? 1 : 0);
  const width = cell.width - (divider === "left" ? 1 : 0);
  const height = cell.height - (divider === "top" ? 1 : 0);
  const sizes = splitSizes(across ? width : height, node.children.length);
  let offset = 0;
  return node.children.map((child, index) => {
    const start = offset;
    offset += sizes[index];
    return {
      node: child,
      divider: index === 0 ? null : across ? "left" : "top",
      x: across ? x + start : x,
      y: across ? y : y + start,
      width: across ? sizes[index] : width,
      height: across ? height : sizes[index],
    };
  });
}

type Arm = "up" | "down" | "left" | "right";

const GLYPHS: Record<string, string> = {
  "up,down": "│",
  "left,right": "─",
  "up,down,right": "├",
  "up,down,left": "┤",
  "down,left,right": "┬",
  "up,left,right": "┴",
  "up,down,left,right": "┼",
};
const ARM_ORDER: Arm[] = ["up", "down", "left", "right"];

interface Line {
  vertical: boolean;
  x: number;
  y: number;
  length: number;
}

function linesOf(cell: Cell): Line[] {
  const own: Line[] =
    cell.divider === "left"
      ? [{ vertical: true, x: cell.x, y: cell.y, length: cell.height }]
      : cell.divider === "top"
        ? [{ vertical: false, x: cell.x, y: cell.y, length: cell.width }]
        : [];
  return [...own, ...splitCells(cell).flatMap(linesOf)];
}

// The glyph for each divider cell, so lines that meet join into ├ ┤ ┬ ┴ ┼ instead of leaving gaps.
// The sidebar's edge runs down column -1, just left of the chat area.
export function dividerGlyphs(
  root: LayoutNode,
  width: number,
  height: number,
): (x: number, y: number) => string {
  const lines = [
    { vertical: true, x: -1, y: 0, length: height },
    ...linesOf({ node: root, divider: null, x: 0, y: 0, width, height }),
  ];
  const arms = new Map<string, Set<Arm>>();
  const key = (x: number, y: number): string => `${x},${y}`;
  const add = (x: number, y: number, ...added: Arm[]): void => {
    const set = arms.get(key(x, y)) ?? new Set<Arm>();
    for (const arm of added) set.add(arm);
    arms.set(key(x, y), set);
  };
  for (const line of lines) {
    for (let step = 0; step < line.length; step++) {
      if (line.vertical) add(line.x, line.y + step, "up", "down");
      else add(line.x + step, line.y, "left", "right");
    }
  }
  const isVertical = (x: number, y: number): boolean =>
    arms.get(key(x, y))?.has("up") ?? false;
  const isHorizontal = (x: number, y: number): boolean =>
    arms.get(key(x, y))?.has("left") ?? false;
  // A line that stops beside another reaches into that line's cell.
  for (const line of lines) {
    if (line.vertical) {
      const end = line.y + line.length;
      if (isHorizontal(line.x, line.y - 1)) add(line.x, line.y - 1, "down");
      if (isHorizontal(line.x, end)) add(line.x, end, "up");
    } else {
      const end = line.x + line.length;
      if (isVertical(line.x - 1, line.y)) add(line.x - 1, line.y, "right");
      if (isVertical(end, line.y)) add(end, line.y, "left");
    }
  }
  return (x, y) => {
    const set = arms.get(key(x, y));
    if (!set) return " ";
    return GLYPHS[ARM_ORDER.filter((arm) => set.has(arm)).join(",")] ?? "┼";
  };
}
