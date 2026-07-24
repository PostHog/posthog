import { X } from "@phosphor-icons/react";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { Box, Flex, ScrollArea, Text, Tooltip } from "@radix-ui/themes";

interface ChannelContextPanelProps {
  channelName?: string;
  body: string;
  onClose: () => void;
}

// Side-panel preview of a channel's CONTEXT.md, opened from the new-task chip.
// Mirrors ChannelContextTab's read-only markdown render, but adds its own header
// + close button since it lives in a ResizableSidebar rather than a task tab.
export function ChannelContextPanel({
  channelName,
  body,
  onClose,
}: ChannelContextPanelProps) {
  return (
    <Flex direction="column" className="h-full min-w-0">
      <Flex
        align="center"
        justify="between"
        gap="2"
        className="shrink-0 border-gray-6 border-b px-4 py-2"
      >
        <Text
          size="2"
          weight="medium"
          className="min-w-0 truncate text-gray-12"
        >
          {channelName ? `${channelName} ` : ""}CONTEXT.md
        </Text>
        <Tooltip content="Close">
          <button
            type="button"
            onClick={onClose}
            aria-label="Close CONTEXT.md panel"
            className="flex size-6 shrink-0 items-center justify-center rounded text-gray-10 hover:bg-gray-4 hover:text-gray-12"
          >
            <X size={14} />
          </button>
        </Tooltip>
      </Flex>
      <ScrollArea type="auto" scrollbars="vertical" className="min-h-0 flex-1">
        <Box p="4">
          <Text className="mb-3 block text-[12px] text-gray-9">
            Included with new tasks in this channel as background context.
          </Text>
          <Box className="text-[13px]">
            <MarkdownRenderer content={body} />
          </Box>
        </Box>
      </ScrollArea>
    </Flex>
  );
}
