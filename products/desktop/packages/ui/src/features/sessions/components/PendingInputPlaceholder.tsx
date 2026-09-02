import { Box, Flex } from "@radix-ui/themes";

/**
 * Non-interactive skeleton sized to match {@link PromptInput} so the chat
 * shell does not jump when the real editor mounts after session init.
 */
export function PendingInputPlaceholder() {
  return (
    <Flex direction="column" gap="1" aria-hidden className="w-full opacity-70">
      <Flex
        align="end"
        className="rounded-(--radius-2) border border-(--gray-5) bg-card"
      >
        <Box className="min-h-[37px] flex-1 px-2 py-2">
          <Box className="h-3 w-2/5 animate-pulse rounded bg-gray-4" />
        </Box>
        <Box className="m-1 h-7 w-7 shrink-0 animate-pulse rounded bg-gray-5" />
      </Flex>
      <Flex align="center" gap="1" className="px-1">
        <Box className="h-6 w-6 animate-pulse rounded bg-gray-4" />
        <Box className="h-6 w-16 animate-pulse rounded bg-gray-4" />
        <Box className="h-6 w-28 animate-pulse rounded bg-gray-4" />
      </Flex>
    </Flex>
  );
}
