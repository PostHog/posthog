import { Eraser } from "@phosphor-icons/react";
import { ChatMarker, ChatMarkerContent, Text } from "@posthog/quill";
import { useChatThreadChrome } from "../chat-thread/chatThreadChrome";

// New thread renders the boundary as a centered separator marker; the legacy
// thread keeps a bordered row so ConversationView is unchanged when the chat
// thread is off (mirrors CompactBoundaryView).
export function ConversationClearedView() {
  const chatChrome = useChatThreadChrome();

  if (chatChrome) {
    return (
      <ChatMarker variant="separator">
        <ChatMarkerContent>Conversation cleared</ChatMarkerContent>
      </ChatMarker>
    );
  }

  return (
    <div className="my-1 flex items-center gap-2 border-gray-6 border-l-2 py-1 pl-3 dark:border-gray-8">
      <Eraser size={14} weight="fill" className="text-gray-9" aria-hidden />
      <Text className="text-[13px] text-gray-11">Conversation cleared</Text>
      <Text className="text-[13px] text-gray-9">
        (earlier messages are no longer in the agent's context)
      </Text>
    </div>
  );
}
