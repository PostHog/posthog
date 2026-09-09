import {
  ChatBubble,
  ChatBubbleContent,
  ChatMessage,
  ChatMessageContent,
  ChatMessageFooter,
} from "@posthog/quill";
import { ComposerWidth } from "@posthog/ui/features/sessions/components/ComposerWidth";
import { UserMessageBody } from "@posthog/ui/features/sessions/components/chat-thread/UserMessageBody";
import { PendingInputPlaceholder } from "@posthog/ui/features/sessions/components/PendingInputPlaceholder";
import {
  CHAT_CONTENT_MAX_WIDTH,
  CHAT_CONTENT_PADDING_INLINE,
} from "@posthog/ui/features/sessions/constants";
import type { UserMessageAttachment } from "@posthog/ui/features/sessions/userMessageTypes";
import { Spinner } from "@posthog/ui/primitives/Spinner";

interface PendingChatViewProps {
  /**
   * The prompt as the live transcript will render it (serialized content with
   * chips), so the bubble looks the same when the transcript replaces it.
   */
  content: string;
  attachments?: UserMessageAttachment[];
}

export function PendingChatView({
  content,
  attachments,
}: PendingChatViewProps) {
  return (
    <div className="absolute inset-0 flex flex-col bg-background">
      <div className="min-h-0 flex-1 overflow-y-auto [scrollbar-gutter:stable]">
        <div
          className="flex w-full flex-col gap-4 py-4 pb-8"
          style={{ paddingInline: CHAT_CONTENT_PADDING_INLINE }}
        >
          <div
            className="mx-auto w-full py-1"
            style={{ maxWidth: CHAT_CONTENT_MAX_WIDTH }}
          >
            <ChatMessage align="end">
              <ChatMessageContent className="gap-1">
                <ChatBubble align="end" className="rounded-lg">
                  <ChatBubbleContent>
                    <UserMessageBody
                      content={content}
                      attachments={attachments}
                    />
                  </ChatBubbleContent>
                </ChatBubble>
                <ChatMessageFooter aria-hidden className="min-h-5" />
              </ChatMessageContent>
            </ChatMessage>
          </div>
          <div
            className="mx-auto flex w-full items-center gap-2 px-2.5"
            style={{ maxWidth: CHAT_CONTENT_MAX_WIDTH }}
          >
            <Spinner size="sm" className="text-accent-11" />
            <span className="text-[13px] text-accent-11">Loading</span>
          </div>
        </div>
      </div>
      <ComposerWidth compact={false}>
        <PendingInputPlaceholder />
      </ComposerWidth>
    </div>
  );
}
