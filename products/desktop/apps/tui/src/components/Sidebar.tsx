import { Box, type DOMElement, Text } from "ink";
import { memo, type ReactElement, type RefObject } from "react";
import type { Indicator, SidebarRow } from "../sidebar";
import { posthogOrange, selectionBackground } from "../theme";
import { todayGlyph } from "../today";
import { Spinner } from "./Spinner";

// PostHog orange, which reads on light and dark terminals alike.
const ORANGE = "#F54E00";

const Label = ({
  text,
  selected = false,
}: {
  text: string;
  selected?: boolean;
}): ReactElement => (
  <Text bold backgroundColor={selected ? selectionBackground() : undefined}>
    {text}
  </Text>
);

// The chat area draws the sidebar's right edge, so its lines can join it.
export const SIDEBAR_WIDTH = 31;
// Narrowed with Ctrl+B: the logo's coloured stripes and a cell either side.
export const NARROW_SIDEBAR_WIDTH = 5;

// Blank rows under the header; clicks on the sidebar skip them.
export const HEADER_GAP = 1;

// The same brand stripes phrocs draws in its header (tools/phrocs/internal/palette).
export const BRAND_STRIPES = ["#1D4AFF", "#F04438", "#F7A501", "#151515"];

const INDICATOR_COLORS: Record<Exclude<Indicator, "working">, string> = {
  // PostHog orange.
  waiting: "#F54E00",
  alive: "green",
  failed: "red",
  asleep: "gray",
};

// A square marks a chat that runs on this machine, a dot one that runs in the cloud, and a cross a failed run, since
// a reply cannot bring that one back.
export function IndicatorGlyph({
  indicator,
  local,
}: {
  indicator: Indicator | null;
  local: boolean;
}): ReactElement {
  // The terminal's own text colour, so the spinner is white on a dark theme and black on a light one.
  if (indicator === "working") return <Spinner color="" />;
  return indicator ? (
    <Text color={INDICATOR_COLORS[indicator]}>
      {indicator === "failed" ? "✗" : local ? "■" : "●"}
    </Text>
  ) : (
    <Text> </Text>
  );
}

function Row({
  row,
  selected,
  hour,
}: {
  row: SidebarRow;
  selected: boolean;
  hour: number;
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
    case "section":
      return (
        <Text>
          <Label text={row.label} />
          {row.label === "Pinned" && <Text color={ORANGE}> ⚲</Text>}
        </Text>
      );
    case "today":
      return (
        <Text wrap="truncate-end">
          <Text
            bold
            backgroundColor={selected ? selectionBackground() : undefined}
          >
            Today
          </Text>
          <Text color={ORANGE}> {todayGlyph(hour)}</Text>
        </Text>
      );
    case "gap":
      // Ink gives an empty string no height, so the gap carries a space.
      return <Text> </Text>;
    case "workspace":
      return (
        <Text wrap="truncate-end">
          <Label text={row.label} selected={selected} />
          {!row.expanded && <Text dimColor> ({row.size})</Text>}
        </Text>
      );
    case "task":
      return (
        <Text wrap="truncate-end">
          {row.nested && <Text dimColor>{row.last ? "╰ " : "├ "}</Text>}
          {row.taskId === null ? (
            // A new chat has no run to show a status for.
            <Text dimColor>• </Text>
          ) : (
            (row.indicator || !row.nested) && (
              <>
                <IndicatorGlyph
                  indicator={row.indicator}
                  local={row.local}
                />{" "}
              </>
            )
          )}
          <Text backgroundColor={selected ? selectionBackground() : undefined}>
            {row.title}
          </Text>
        </Text>
      );
    case "loading":
      return <Spinner label="Loading cloud runs" />;
    case "signedOut":
      return <Text dimColor>Signed out · type /login</Text>;
    case "empty":
      return <Text dimColor>No work yet</Text>;
    case "viewMore":
      return (
        <Text
          dimColor={!selected}
          backgroundColor={selected ? selectionBackground() : undefined}
        >
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

// The same rows at the logo's width: glyphs stand in for names, and the dots and tree stay as they are.
function NarrowRow({
  row,
  selected,
  hour,
}: {
  row: SidebarRow;
  selected: boolean;
  hour: number;
}): ReactElement {
  switch (row.kind) {
    case "heading":
      return (
        <Text>
          {BRAND_STRIPES.slice(0, -1).map((color) => (
            <Text key={color} backgroundColor={color}>
              {" "}
            </Text>
          ))}
        </Text>
      );
    case "section":
      return <Label text={row.label === "Pinned" ? "Pin" : "All"} />;
    case "today":
      return (
        <Text
          color={ORANGE}
          backgroundColor={selected ? selectionBackground() : undefined}
        >
          {todayGlyph(hour)}
        </Text>
      );
    case "gap":
      return <Text> </Text>;
    case "workspace":
      return (
        <Text
          bold
          backgroundColor={selected ? selectionBackground() : undefined}
        >
          ▦
        </Text>
      );
    case "task":
      return (
        <Text>
          {row.nested && <Text dimColor>{row.last ? "╰ " : "├ "}</Text>}
          <Text backgroundColor={selected ? selectionBackground() : undefined}>
            {row.taskId === null ? (
              <Text dimColor>•</Text>
            ) : (
              <IndicatorGlyph indicator={row.indicator} local={row.local} />
            )}
          </Text>
        </Text>
      );
    case "loading":
      return <Spinner />;
    case "viewMore":
      return (
        <Text
          dimColor={!selected}
          backgroundColor={selected ? selectionBackground() : undefined}
        >
          …
        </Text>
      );
    case "error":
      return <Text color="red">!</Text>;
    case "signedOut":
    case "empty":
      return <Text dimColor>·</Text>;
  }
}

function rowKey(row: SidebarRow, index: number): string {
  if (row.kind === "task")
    return `${row.pinned ? "pinned" : (row.paneId ?? "work")}:${row.taskId}`;
  if (row.kind === "workspace") return row.workspaceId;
  return `${row.kind}:${index}`;
}

export const Sidebar = memo(function Sidebar({
  boxRef,
  notice,
  rows,
  focused,
  selectedIndex,
  activePaneId,
  narrow = false,
  // The hour the Today row's sky follows; the clock's, unless a test pins it.
  hour = new Date().getHours(),
}: {
  boxRef?: RefObject<DOMElement | null>;
  notice: string | null;
  rows: SidebarRow[];
  focused: boolean;
  selectedIndex: number;
  activePaneId: string | null;
  narrow?: boolean;
  hour?: number;
}): ReactElement {
  // With focus the bar follows the cursor; without it, it marks the focused pane's task.
  // Unfocused, the open chat's row is marked; a folded workspace's title stands in for the chat it hides.
  const highlighted = (row: SidebarRow, index: number): boolean =>
    focused
      ? index === selectedIndex
      : row.kind === "workspace"
        ? !row.expanded && index === selectedIndex
        : (row.kind === "task" || row.kind === "today") &&
          row.paneId !== null &&
          row.paneId === activePaneId;

  return (
    <Box
      ref={boxRef}
      width={narrow ? NARROW_SIDEBAR_WIDTH : SIDEBAR_WIDTH}
      flexShrink={0}
      flexDirection="column"
      paddingX={1}
      overflow="hidden"
    >
      {rows.map((row, index) => (
        <Box
          key={rowKey(row, index)}
          marginBottom={row.kind === "heading" ? HEADER_GAP : 0}
        >
          <Text wrap="truncate-end">
            {narrow ? (
              <NarrowRow
                row={row}
                selected={highlighted(row, index)}
                hour={hour}
              />
            ) : (
              <Row row={row} selected={highlighted(row, index)} hour={hour} />
            )}
          </Text>
        </Box>
      ))}
      <Box flexGrow={1} />
      <Text
        dimColor={!notice}
        color={notice ? posthogOrange() : undefined}
        wrap="truncate-end"
      >
        {narrow
          ? notice
            ? "●"
            : "^B"
          : (notice ?? "^N new · ^\\ split · /help")}
      </Text>
    </Box>
  );
});
