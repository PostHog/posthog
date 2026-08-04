import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import type { ToolGroupItem } from "@posthog/ui/features/sessions/components/chat-thread/ToolGroup";
import { extractCanvasInstructions } from "@posthog/ui/features/sessions/components/session-update/canvasInstructions";
import { extractChannelContext } from "@posthog/ui/features/sessions/components/session-update/channelContext";
import { extractCustomInstructions } from "@posthog/ui/features/sessions/components/session-update/customInstructions";
import { extractOrchestrationInstructions } from "@posthog/ui/features/sessions/components/session-update/orchestrationInstructions";

function visiblePromptContent(content: string): string {
  const channelContext = extractChannelContext(content);
  const afterChannelContext = channelContext?.stripped ?? content;
  const canvasInstructions = extractCanvasInstructions(afterChannelContext);
  const afterCanvasInstructions =
    canvasInstructions?.stripped ?? afterChannelContext;
  const orchestrationInstructions = extractOrchestrationInstructions(
    afterCanvasInstructions,
  );
  const afterOrchestrationInstructions =
    orchestrationInstructions?.stripped ?? afterCanvasInstructions;
  const customInstructions = extractCustomInstructions(
    afterOrchestrationInstructions,
  );
  return customInstructions?.stripped ?? afterOrchestrationInstructions;
}

/**
 * Plain-text transcript of a turn's visible prompt and agent prose, in order.
 *
 * Tool calls, thoughts and status rows are left out — this is for pasting an answer somewhere else,
 * not for reproducing the run. Returns null when the rows carry no prose.
 */
export function buildTurnCopyText(
  items: Array<ConversationItem | ToolGroupItem>,
): string | null {
  const parts: string[] = [];

  for (const item of items) {
    if (item.type === "user_message") {
      const content = visiblePromptContent(item.content).trim();
      if (content) parts.push(content);
      continue;
    }
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
