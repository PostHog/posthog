import {
  AcpChatThread,
  type AcpChatThreadProps,
} from "@posthog/ui/features/sessions/components/chat-thread/ChatThread";

export function ThreadView(props: AcpChatThreadProps) {
  return <AcpChatThread {...props} />;
}
