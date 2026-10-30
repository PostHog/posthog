import { Box, type DOMElement } from "ink";
import type { ReactElement } from "react";
import { type LayoutNode, type PaneNode, paneIds, splitSizes } from "../layout";

type Divider = "left" | "top" | null;

// A split draws one line between neighbours: left of each column after the first, above each row after the first.
function dividerProps(divider: Divider) {
  return divider
    ? {
        borderStyle: "single" as const,
        borderColor: "gray",
        borderDimColor: true,
        borderTop: divider === "top",
        borderLeft: divider === "left",
        borderRight: false,
        borderBottom: false,
      }
    : {};
}

// Lays out a workspace's splits and draws each pane in its cell.
// Splits get whole-cell sizes worked out here; flex layout rounds half cells and leaves gaps.
export function PaneTree({
  node,
  divider = null,
  width,
  height,
  renderPane,
  onPaneBox,
}: {
  node: LayoutNode;
  divider?: Divider;
  width: number;
  height: number;
  renderPane: (pane: PaneNode) => ReactElement;
  onPaneBox: (paneId: string, element: DOMElement | null) => void;
}): ReactElement {
  if (node.kind === "pane") {
    return (
      <Box
        ref={(element) => onPaneBox(node.id, element)}
        width={width}
        height={height}
        flexDirection="column"
        {...dividerProps(divider)}
      >
        {renderPane(node)}
      </Box>
    );
  }
  const across = node.direction === "row";
  // This split's own divider takes a row or column before its children share the rest.
  const innerWidth = width - (divider === "left" ? 1 : 0);
  const innerHeight = height - (divider === "top" ? 1 : 0);
  const sizes = splitSizes(
    across ? innerWidth : innerHeight,
    node.children.length,
  );
  return (
    <Box
      flexDirection={node.direction}
      width={width}
      height={height}
      {...dividerProps(divider)}
    >
      {node.children.map((child, index) => (
        <PaneTree
          key={child.kind === "pane" ? child.id : paneIds(child).join()}
          node={child}
          divider={index === 0 ? null : across ? "left" : "top"}
          width={across ? sizes[index] : innerWidth}
          height={across ? innerHeight : sizes[index]}
          renderPane={renderPane}
          onPaneBox={onPaneBox}
        />
      ))}
    </Box>
  );
}
