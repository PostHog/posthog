import { ChatMarker, ChatMarkerContent } from "@posthog/quill";

export function ConversationClearedView() {
  return (
    <ChatMarker variant="separator">
      <ChatMarkerContent>Conversation cleared</ChatMarkerContent>
    </ChatMarker>
  );
}
