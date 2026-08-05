import type { AcpMessage } from "@posthog/shared";
import type { AgentApprovalRequest } from "@posthog/shared/agent-platform-types";
import { createStore } from "zustand/vanilla";

/**
 * Domain state for deployed-agent live chats. Keyed by an opaque `chatId` so
 * several chats can be live at once — e.g. the always-on agent builder dock
 * (`"agent-builder"`) and a per-agent chat (`"preview:<slug>"`) side by side.
 * The UI hook (`useAgentChat`) owns the transport (run/send/cancel + the SSE
 * loop, via the api-client) and pumps mapped `AcpMessage`s in here; components
 * read one chat by id and render it through `ConversationView`.
 */

export type AgentChatStatus =
  | "idle"
  | "starting"
  | "streaming"
  | "awaiting_input"
  | "completed"
  | "failed"
  | "cancelled";

export interface AgentChatState {
  /** Which agent this chat targets (slug), or null when idle. */
  agentKey: string | null;
  sessionId: string | null;
  status: AgentChatStatus;
  /** Accumulated ACP messages (mapper output) for ConversationView. */
  messages: AcpMessage[];
  /**
   * The approval-gated tool call this chat is currently paused on, or null. Set
   * by the service when it sees a `queued` approval marker on the stream (it
   * one-shot-fetches the full request from the ingress); cleared when the marker
   * resolves or the user decides. Drives the inline approval card — no polling.
   */
  pendingApproval: AgentApprovalRequest | null;
  error: string | null;
}

/**
 * Retention cap per chat. A live chat streams an AcpMessage per chunk, so an
 * unbounded array grows without limit on long sessions; past this the oldest
 * messages fall off (the transcript of record lives server-side).
 */
export const MAX_CHAT_MESSAGES = 2000;

export const EMPTY_CHAT: AgentChatState = {
  agentKey: null,
  sessionId: null,
  status: "idle",
  messages: [],
  pendingApproval: null,
  error: null,
};

interface AgentChatStore {
  /** All live chats, keyed by `chatId`. */
  chats: Record<string, AgentChatState>;

  /** Reset `chatId` for a brand-new chat against `agentKey`. */
  begin: (chatId: string, agentKey: string) => void;
  setSessionId: (chatId: string, sessionId: string) => void;
  setStatus: (chatId: string, status: AgentChatStatus) => void;
  appendMessages: (chatId: string, messages: AcpMessage[]) => void;
  setPendingApproval: (
    chatId: string,
    approval: AgentApprovalRequest | null,
  ) => void;
  setError: (chatId: string, error: string | null) => void;
  reset: (chatId: string) => void;
}

export const agentChatStore = createStore<AgentChatStore>((set) => {
  const patch = (
    chatId: string,
    next: Partial<AgentChatState>,
  ): ((s: AgentChatStore) => AgentChatStore) => {
    return (s) => ({
      ...s,
      chats: {
        ...s.chats,
        [chatId]: { ...(s.chats[chatId] ?? EMPTY_CHAT), ...next },
      },
    });
  };

  return {
    chats: {},
    begin: (chatId, agentKey) =>
      set(patch(chatId, { ...EMPTY_CHAT, agentKey, status: "starting" })),
    setSessionId: (chatId, sessionId) => set(patch(chatId, { sessionId })),
    setStatus: (chatId, status) => set(patch(chatId, { status })),
    appendMessages: (chatId, messages) =>
      set((s) => {
        if (messages.length === 0) return s;
        const cur = s.chats[chatId] ?? EMPTY_CHAT;
        const appended = [...cur.messages, ...messages];
        return {
          ...s,
          chats: {
            ...s.chats,
            [chatId]: {
              ...cur,
              messages:
                appended.length > MAX_CHAT_MESSAGES
                  ? appended.slice(-MAX_CHAT_MESSAGES)
                  : appended,
            },
          },
        };
      }),
    setPendingApproval: (chatId, approval) =>
      set(patch(chatId, { pendingApproval: approval })),
    setError: (chatId, error) => set(patch(chatId, { error })),
    reset: (chatId) => set(patch(chatId, { ...EMPTY_CHAT })),
  };
});
