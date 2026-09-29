import { Box, type DOMElement, Text } from "ink";
import type { ReactElement, RefObject } from "react";
import type { Indicator, SidebarRow } from "../sidebar";
import { Spinner } from "./Spinner";

export const SIDEBAR_WIDTH = 32;

// Blank rows under the header; clicks on the sidebar skip them.
export const HEADER_GAP = 1;

// The same brand stripes phrocs draws in its header (tools/phrocs/internal/palette).
const BRAND_STRIPES = ["#1D4AFF", "#F04438", "#F7A501", "#151515"];

const INDICATOR_COLORS: Record<Exclude<Indicator, "working">, string> = {
  alive: "green",
  failed: "red",
  asleep: "gray",
};

function IndicatorGlyph({
  indicator,
}: {
  indicator: Indicator | null;
}): ReactElement {
  if (indicator === "working") return <Spinner />;
  return indicator ? (
    <Text color={INDICATOR_COLORS[indicator]}>●</Text>
  ) : (
    <Text> </Text>
  );
}

function Row({
  row,
  selected,
}: {
  row: SidebarRow;
  selected: boolean;
}): ReactElement {
  switch (row.kind) {
    case "heading":
      return (
        <Text>
          {BRAND_STRIPES.map((color) => (
            <Text key={color} backgroundColor={color}>
              {" "}
            </Text>
          ))}
          <Text bold> PostHog</Text>
        </Text>
      );
    case "workspace":
      return (
        <Text wrap="truncate-end">
          <Text bold inverse={selected}>
            {row.label}
          </Text>
          {!row.expanded && <Text dimColor> ({row.size})</Text>}
        </Text>
      );
    case "task":
      return (
        <Text wrap="truncate-end">
          {row.nested && <Text dimColor>{row.last ? "└ " : "├ "}</Text>}
          {(row.indicator || !row.nested) && (
            <>
              <IndicatorGlyph indicator={row.indicator} />{" "}
            </>
          )}
          <Text inverse={selected}>{row.title}</Text>
        </Text>
      );
    case "loading":
      return <Spinner label="Loading cloud runs" />;
    case "empty":
      return <Text dimColor>No work yet</Text>;
    case "viewMore":
      return (
        <Text dimColor={!selected} inverse={selected}>
          View more
        </Text>
      );
    case "error":
      return (
        <Text color="red" wrap="truncate-end">
          Couldn't load work: {row.message}
        </Text>
      );
  }
}

function rowKey(row: SidebarRow, index: number): string {
  if (row.kind === "task") return `${row.paneId ?? "work"}:${row.taskId}`;
  if (row.kind === "workspace") return row.workspaceId;
  return `${row.kind}:${index}`;
}

export function Sidebar({
  boxRef,
  notice,
  rows,
  focused,
  selectedIndex,
  activePaneId,
}: {
  boxRef?: RefObject<DOMElement | null>;
  notice: string | null;
  rows: SidebarRow[];
  focused: boolean;
  selectedIndex: number;
  activePaneId: string | null;
}): ReactElement {
  // With focus the bar follows the cursor; without it, it marks the focused pane's task.
  const highlighted = (row: SidebarRow, index: number): boolean =>
    focused
      ? index === selectedIndex
      : row.kind === "task" &&
        row.paneId !== null &&
        row.paneId === activePaneId;

  return (
    <Box
      ref={boxRef}
      width={SIDEBAR_WIDTH}
      flexShrink={0}
      flexDirection="column"
      borderStyle="single"
      borderColor="gray"
      borderDimColor
      borderTop={false}
      borderBottom={false}
      borderLeft={false}
      overflow="hidden"
    >
      {rows.map((row, index) => (
        <Box
          key={rowKey(row, index)}
          marginBottom={row.kind === "heading" ? HEADER_GAP : 0}
        >
          <Text dimColor={!focused} wrap="truncate-end">
            <Row row={row} selected={highlighted(row, index)} />
          </Text>
        </Box>
      ))}
      <Box flexGrow={1} />
      <Text dimColor={!notice} wrap="truncate-end">
        {notice ?? "^N new · ^S split · ^C^C close"}
      </Text>
    </Box>
  );
}
