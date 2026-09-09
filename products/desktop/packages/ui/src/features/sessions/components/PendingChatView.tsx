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
import {
  SessionStartupStatus,
  type SessionStartupStatusProps,
} from "./SessionStartupStatus";

interface PendingChatViewProps
  extends Omit<SessionStartupStatusProps, "showDetails"> {
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
  executionTarget,
  phase,
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
            className="mx-auto flex w-full flex-col gap-3 px-2.5"
            style={{ maxWidth: CHAT_CONTENT_MAX_WIDTH }}
          >
            <SessionStartupStatus
              executionTarget={executionTarget}
              phase={phase}
            />
            <span className="text-gray-11 text-xs">
              Your prompt is saved with this task. You do not need to submit it
              again.
            </span>
          </div>
        </div>
      </div>
      <ComposerWidth compact={false}>
        <PendingInputPlaceholder />
      </ComposerWidth>
    </div>
  );
}
