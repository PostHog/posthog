import { Box, Text } from "ink";
import type { ReactElement } from "react";
import type { Indicator, SidebarRow } from "../sidebar";
import { Spinner } from "./Spinner";

export const SIDEBAR_WIDTH = 32;

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

function Row({ row }: { row: SidebarRow }): ReactElement {
  switch (row.kind) {
    case "heading":
      return <Text bold>{row.label}</Text>;
    case "workspace":
      return (
        <Text wrap="truncate-end">
          {row.expanded ? "▾" : "▸"} {row.label}
        </Text>
      );
    case "task":
      return (
        <Box paddingLeft={row.nested ? 2 : 0}>
          <Text wrap="truncate-end">
            <IndicatorGlyph indicator={row.indicator} /> {row.title}
          </Text>
        </Box>
      );
    case "loading":
      return <Spinner label="Loading" />;
    case "empty":
      return <Text dimColor>No work yet</Text>;
    case "viewMore":
      return <Text dimColor>View more</Text>;
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
  rows,
  focused,
  selectedIndex,
  activePaneId,
}: {
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
      width={SIDEBAR_WIDTH}
      flexShrink={0}
      flexDirection="column"
      borderStyle="single"
      borderColor={focused ? "white" : "gray"}
      borderTop={false}
      borderBottom={false}
      borderLeft={false}
      overflow="hidden"
    >
      {rows.map((row, index) => (
        <Box
          key={rowKey(row, index)}
          marginTop={row.kind === "heading" && index > 0 ? 1 : 0}
          backgroundColor={highlighted(row, index) ? "#3a3a3a" : undefined}
        >
          <Row row={row} />
        </Box>
      ))}
      <Box flexGrow={1} />
      <Text dimColor wrap="truncate-end">
        tab focus · ^S split · ^C quit
      </Text>
    </Box>
  );
}
