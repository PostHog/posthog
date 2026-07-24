import { Box, Flex } from "@radix-ui/themes";

/**
 * Non-interactive skeleton sized to match {@link PromptInput} so the chat
 * shell does not jump when the real editor mounts after session init.
 */
export function PendingInputPlaceholder() {
  return (
    <Box
      aria-hidden
      className="w-full rounded-(--radius-2) border border-(--gray-5) bg-card opacity-70"
    >
      <Box className="min-h-[50px] px-2 py-2">
        <Box className="h-3 w-2/5 animate-pulse rounded bg-gray-4" />
      </Box>
      <Flex
        align="center"
        gap="2"
        className="border-(--gray-4) border-t px-2 py-1.5"
      >
        <Box className="h-5 w-5 animate-pulse rounded bg-gray-4" />
        <Box className="h-5 w-16 animate-pulse rounded bg-gray-4" />
        <Box className="h-5 w-20 animate-pulse rounded bg-gray-4" />
        <Box className="ml-auto h-6 w-6 animate-pulse rounded bg-gray-5" />
      </Flex>
    </Box>
  );
}
