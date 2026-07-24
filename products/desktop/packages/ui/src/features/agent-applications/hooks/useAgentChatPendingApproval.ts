import { agentChatStore } from "@posthog/core/agent-chat/agentChatStore";
import type { AgentApprovalRequest } from "@posthog/shared/agent-platform-types";
import { useStore } from "zustand";

/**
 * The approval-gated tool call this chat is currently paused on, or null —
 * what drives the inline approval card in the chat pane / agent builder dock.
 *
 * The chat service maintains it from the stream: a `queued` approval marker
 * triggers a one-shot fetch of the full request from the ingress, and a
 * resolve/decide clears it. So the card is push-driven (no polling) and works
 * from any project — the detail comes from the slug-routed ingress, not the
 * project-scoped console API.
 */
export function useAgentChatPendingApproval(
  chatId: string,
): AgentApprovalRequest | null {
  return useStore(
    agentChatStore,
    (s) => s.chats[chatId]?.pendingApproval ?? null,
  );
}
