import type { ConversationViewProps } from "@posthog/ui/features/sessions/components/ConversationView";
import { AcpChatThread } from "@posthog/ui/features/sessions/components/chat-thread/ChatThread";

export function ThreadView(props: ConversationViewProps) {
  return <AcpChatThread {...props} />;
}
