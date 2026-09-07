import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import type { ToolGroupItem } from "@posthog/ui/features/sessions/components/chat-thread/ToolGroup";

/**
 * Plain-text transcript of a turn's agent prose, in order.
 *
 * User prompts, tool calls, thoughts and status rows are left out — this is for pasting an answer
 * somewhere else, not for reproducing the run. Returns null when the rows carry no prose.
 */
export function buildTurnCopyText(
  items: Array<ConversationItem | ToolGroupItem>,
): string | null {
  const parts: string[] = [];

  for (const item of items) {
    if (item.type !== "session_update") continue;
    const update = item.update;
    if (update.sessionUpdate !== "agent_message_chunk") continue;
    if (update.content.type !== "text") continue;
    const text = update.content.text.trim();
    if (text) parts.push(text);
  }

  if (parts.length === 0) return null;
  return parts.join("\n\n");
}
