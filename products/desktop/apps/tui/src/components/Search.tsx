import { Box, Text, useWindowSize } from "ink";
import type { ReactElement } from "react";
import type { SearchState } from "../hooks/useSearch";
import { IndicatorGlyph } from "./Sidebar";
import { Spinner } from "./Spinner";

// Screen rows the results do not get: the query, the gap under it, the key hints, and the spare bottom row.
const CHROME_ROWS = 4;

export function Search({
  search: { query, rows, error, index },
}: {
  search: SearchState;
}): ReactElement {
  const { rows: height } = useWindowSize();
  const count = Math.max(1, height - CHROME_ROWS);
  // The window follows the cursor, so a long list scrolls instead of running off the screen.
  const start = Math.max(
    0,
    Math.min(index - count + 1, (rows?.length ?? 0) - count),
  );

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
      ) : rows === null ? (
        <Spinner label="Searching" />
      ) : rows.length === 0 ? (
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
      <Box flexGrow={1} />
      <Text dimColor>↑↓ move · Enter open · Esc close</Text>
    </Box>
  );
}
