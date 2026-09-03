import { Brain } from "@phosphor-icons/react";
import { ChatBubble, ChatBubbleContent, ChatMessage } from "@posthog/quill";
import { ChatMarkdown } from "@posthog/ui/features/sessions/components/chat-thread/ChatMarkdown";
import { PendingInputPlaceholder } from "@posthog/ui/features/sessions/components/PendingInputPlaceholder";
import { UserMessageAttachments } from "@posthog/ui/features/sessions/components/UserMessageAttachments";
import {
  CHAT_CONTENT_MAX_WIDTH,
  CHAT_CONTENT_PADDING_INLINE,
} from "@posthog/ui/features/sessions/constants";
import type { UserMessageAttachment } from "@posthog/ui/features/sessions/userMessageTypes";
import { Box, Flex, Text } from "@radix-ui/themes";

interface PendingChatViewProps {
  promptText: string;
  attachments?: UserMessageAttachment[];
  /**
   * Replaces the default "Starting task…" status line with the live run
   * state, so a cloud task reads "Starting the sandbox…" while it boots.
   */
  statusText?: string;
}

/**
 * The prompt shown inside the chat while its task is being created or is
 * booting. The message renders in the same bubble and column geometry as the
 * live thread, so the transcript replacing it changes nothing the user sees.
 */
export function PendingChatView({
  promptText,
  attachments,
  statusText,
}: PendingChatViewProps) {
  return (
    <Flex direction="column" className="absolute inset-0 bg-background">
      <Box className="min-h-0 flex-1 overflow-y-auto">
        <Box
          className="mx-auto flex w-full flex-col gap-4 py-4"
          style={{
            maxWidth: CHAT_CONTENT_MAX_WIDTH,
            paddingInline: CHAT_CONTENT_PADDING_INLINE,
          }}
        >
          <Box className="px-2.5 pt-1">
            <ChatMessage align="end">
              <ChatBubble align="end" className="rounded-lg">
                <ChatBubbleContent>
                  <ChatMarkdown content={promptText} />
                  {attachments && attachments.length > 0 && (
                    <Box className="mt-1.5">
                      <UserMessageAttachments attachments={attachments} />
                    </Box>
                  )}
                </ChatBubbleContent>
              </ChatBubble>
            </ChatMessage>
          </Box>
          <Flex align="center" gap="2" className="px-2.5">
            <Brain size={12} className="ph-pulse text-accent-11" />
            <Text className="text-[13px] text-accent-11">
              {statusText ?? "Starting task..."}
            </Text>
          </Flex>
        </Box>
      </Box>
      <Box
        className="mx-auto w-full p-2"
        style={{ maxWidth: CHAT_CONTENT_MAX_WIDTH }}
      >
        <PendingInputPlaceholder />
      </Box>
    </Flex>
  );
}
