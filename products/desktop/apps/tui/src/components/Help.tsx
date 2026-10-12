import { Box, Text } from "ink";
import type { ReactElement } from "react";
import { HELP } from "../help";

const KEY_WIDTH = 16;

export function Help(): ReactElement {
  return (
    <Box flexGrow={1} flexDirection="column" paddingX={1} paddingBottom={1}>
      <Text bold>Keyboard shortcuts</Text>
      <Text dimColor>
        Cmd works in place of Ctrl where the terminal passes it on.
      </Text>
      {HELP.map((group) => (
        <Box key={group.title} flexDirection="column">
          <Text> </Text>
          <Text bold>{group.title}</Text>
          {group.rows.map((row) => (
            <Box key={row.keys}>
              <Box width={KEY_WIDTH}>
                <Text>{row.keys}</Text>
              </Box>
              <Text dimColor wrap="truncate-end">
                {row.does}
              </Text>
            </Box>
          ))}
        </Box>
      ))}
      <Box flexGrow={1} />
      <Text dimColor>Esc close</Text>
    </Box>
  );
}
