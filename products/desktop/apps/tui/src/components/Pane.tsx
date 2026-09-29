import { Box, Text } from "ink";
import type { ReactElement } from "react";

export function Pane({
  title,
  focused,
}: {
  title: string;
  focused: boolean;
}): ReactElement {
  return (
    <Box flexGrow={1} paddingX={1}>
      <Text bold={focused} dimColor={!focused} wrap="truncate-end">
        {title}
      </Text>
    </Box>
  );
}
