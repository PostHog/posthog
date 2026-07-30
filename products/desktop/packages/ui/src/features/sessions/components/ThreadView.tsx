import {
  ConversationView,
  type ConversationViewProps,
} from "@posthog/ui/features/sessions/components/ConversationView";
import { AcpChatThread } from "@posthog/ui/features/sessions/components/chat-thread/ChatThread";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";

export function ThreadView(props: ConversationViewProps) {
  const useNewChatThread = useSettingsStore((state) => state.useNewChatThread);

  return useNewChatThread ? (
    <AcpChatThread {...props} />
  ) : (
    <ConversationView {...props} />
  );
}
