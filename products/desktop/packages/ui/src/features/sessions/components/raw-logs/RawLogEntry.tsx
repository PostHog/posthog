import { Copy } from "@phosphor-icons/react";
import type { AcpMessage } from "@posthog/shared";
import { Box, Code, Flex, IconButton, Text } from "@radix-ui/themes";

interface RawLogEntryProps {
  event: AcpMessage;
  index: number;
  onCopy: (text: string) => void;
}

export function RawLogEntry({ event, index, onCopy }: RawLogEntryProps) {
  const json = JSON.stringify(event, null, 2);

  return (
    <Box className="relative rounded p-2">
      <Flex justify="between" align="center" mb="1">
        <Text color="gray" className="text-[13px]">
          Event #{index}
        </Text>
        <IconButton
          size="1"
          variant="ghost"
          color="gray"
          onClick={() => onCopy(json)}
        >
          <Copy size={12} />
        </IconButton>
      </Flex>
      <Code className="block overflow-x-auto whitespace-pre text-[13px]">
        {json}
      </Code>
    </Box>
  );
}
