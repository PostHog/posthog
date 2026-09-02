import type { ConversationViewProps } from "@posthog/ui/features/sessions/components/ConversationView";
import { AcpChatThread } from "@posthog/ui/features/sessions/components/chat-thread/ChatThread";

/** Props still take `ConversationView`'s shape until that component is deleted. */
type ThreadViewProps = ConversationViewProps & {
  /** See `SharedChatThreadProps.groupToolCalls`. */
  groupToolCalls?: boolean;
};

export function ThreadView(props: ThreadViewProps) {
  return <AcpChatThread {...props} />;
}
