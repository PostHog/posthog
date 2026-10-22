import { Box, type DOMElement, Text } from "ink";
import type { ReactElement } from "react";
import { type Cell, splitCells } from "../dividers";
import { type PaneNode, paneIds } from "../layout";

export type Glyph = (x: number, y: number) => string;

// One column of divider glyphs, drawn from the chat area's joined lines.
export function DividerColumn({
  x,
  y,
  height,
  glyph,
}: {
  x: number;
  y: number;
  height: number;
  glyph: Glyph;
}): ReactElement {
  const rows = Array.from({ length: height }, (_, row) => glyph(x, y + row));
  return (
    <Box width={1} height={height} flexShrink={0}>
      <Text color="gray" dimColor>
        {rows.join("\n")}
      </Text>
    </Box>
  );
}

function DividerRow({
  x,
  y,
  width,
  glyph,
}: {
  x: number;
  y: number;
  width: number;
  glyph: Glyph;
}): ReactElement {
  const columns = Array.from({ length: width }, (_, column) =>
    glyph(x + column, y),
  );
  return (
    <Text color="gray" dimColor wrap="truncate-end">
      {columns.join("")}
    </Text>
  );
}

// Lays out a workspace's splits and draws each pane in its cell, with the dividers between them.
export function PaneTree({
  cell,
  glyph,
  renderPane,
  onPaneBox,
}: {
  cell: Cell;
  glyph: Glyph;
  renderPane: (pane: PaneNode) => ReactElement;
  onPaneBox: (paneId: string, element: DOMElement | null) => void;
}): ReactElement {
  const { node, divider, x, y, width, height } = cell;
  const content =
    node.kind === "pane" ? (
      <Box
        width={width - (divider === "left" ? 1 : 0)}
        height={height - (divider === "top" ? 1 : 0)}
        flexDirection="column"
      >
        {renderPane(node)}
      </Box>
    ) : (
      <Box flexDirection={node.direction} flexGrow={1}>
        {splitCells(cell).map((child) => (
          <PaneTree
            key={
              child.node.kind === "pane"
                ? child.node.id
                : paneIds(child.node).join()
            }
            cell={child}
            glyph={glyph}
            renderPane={renderPane}
            onPaneBox={onPaneBox}
          />
        ))}
      </Box>
    );
  return (
    <Box
      ref={
        node.kind === "pane"
          ? (element) => onPaneBox(node.id, element)
          : undefined
      }
      width={width}
      height={height}
      flexShrink={0}
      flexDirection={divider === "left" ? "row" : "column"}
    >
      {divider === "left" && (
        <DividerColumn x={x} y={y} height={height} glyph={glyph} />
      )}
      {divider === "top" && (
        <DividerRow x={x} y={y} width={width} glyph={glyph} />
      )}
      {content}
    </Box>
  );
}
