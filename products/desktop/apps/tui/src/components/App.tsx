import { Box, Text } from "ink";
import type { ReactElement } from "react";

export function App(): ReactElement {
  return (
    <Box>
      <Box
        width={32}
        borderStyle="single"
        borderColor="gray"
        borderTop={false}
        borderBottom={false}
        borderLeft={false}
      >
        <Text bold>Work</Text>
      </Box>
    </Box>
  );
}
