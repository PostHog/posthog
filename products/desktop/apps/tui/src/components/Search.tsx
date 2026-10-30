import { Box, Text, useWindowSize } from "ink";
import type { ReactElement } from "react";
import type { SearchState } from "../hooks/useSearch";
import { IndicatorGlyph } from "./Sidebar";
import { Spinner } from "./Spinner";

// Rows the results do not get: the query, the gap under it, the key hints, and the spare bottom row.
const CHROME_ROWS = 4;

// The task search, full screen or in a pane that gives it its height.
export function Search({
  search: { query, rows, loading, error, index },
  height,
}: {
  search: SearchState;
  height?: number;
}): ReactElement {
  const window = useWindowSize();
  const count = Math.max(
    1,
    (height ?? window.rows) - CHROME_ROWS - (loading ? 1 : 0),
  );
  // The window follows the cursor, so a long list scrolls instead of running off the screen.
  const start = Math.max(0, Math.min(index - count + 1, rows.length - count));

  return (
    <Box flexGrow={1} flexDirection="column" paddingX={1} paddingBottom={1}>
      <Text wrap="truncate-start">
        <Text bold>Search tasks</Text> ❯ {query}
        <Text inverse> </Text>
      </Text>
      <Text> </Text>
      {error ? (
        <Text color="red" wrap="truncate-end">
          Couldn't search tasks: {error}
        </Text>
      ) : rows.length === 0 && !loading ? (
        <Text dimColor>No tasks found</Text>
      ) : (
        rows.slice(start, start + count).map((row, offset) => (
          <Box key={row.taskId} gap={2}>
            <Box flexGrow={1} flexShrink={1}>
              <Text wrap="truncate-end">
                <IndicatorGlyph indicator={row.indicator} local={row.local} />{" "}
                <Text inverse={start + offset === index}>{row.title}</Text>
              </Text>
            </Box>
            <Box flexShrink={0}>
              <Text dimColor>{row.age}</Text>
            </Box>
          </Box>
        ))
      )}
      {loading && !error && <Spinner label="Searching" />}
      <Box flexGrow={1} />
      <Text dimColor>↑↓ move · Enter open · Esc close</Text>
    </Box>
  );
}
