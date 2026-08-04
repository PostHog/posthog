import type { ConversationViewProps } from "@posthog/ui/features/sessions/components/ConversationView";
import { AcpChatThread } from "@posthog/ui/features/sessions/components/chat-thread/ChatThread";

/** Props still ride the older shape while `ConversationView` is around to be deleted. */
type ThreadViewProps = ConversationViewProps & {
  /** See `SharedChatThreadProps.groupToolCalls`. */
  groupToolCalls?: boolean;
};

export function ThreadView(props: ThreadViewProps) {
  return <AcpChatThread {...props} />;
}
