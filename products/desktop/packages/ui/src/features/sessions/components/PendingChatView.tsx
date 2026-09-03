import { Brain } from "@phosphor-icons/react";
import { ChatBubble, ChatBubbleContent, ChatMessage } from "@posthog/quill";
import { UserMessageBody } from "@posthog/ui/features/sessions/components/chat-thread/UserMessageBody";
import { PendingInputPlaceholder } from "@posthog/ui/features/sessions/components/PendingInputPlaceholder";
import {
  CHAT_CONTENT_MAX_WIDTH,
  CHAT_CONTENT_PADDING_INLINE,
} from "@posthog/ui/features/sessions/constants";
import type { UserMessageAttachment } from "@posthog/ui/features/sessions/userMessageTypes";
import { Box, Flex, Text } from "@radix-ui/themes";

interface PendingChatViewProps {
  /**
   * The prompt as the live transcript will render it (serialized content with
   * chips), so the bubble looks the same when the transcript replaces it.
   */
  content: string;
  attachments?: UserMessageAttachment[];
  statusText?: string;
}

export function PendingChatView({
  content,
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
                  <UserMessageBody
                    content={content}
                    attachments={attachments}
                  />
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
