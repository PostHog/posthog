import type { AcpMessage } from "@posthog/shared";
import type {
  AgentConversationMessage,
  AgentSessionEvent,
} from "@posthog/shared/agent-platform-types";

export const AGENT_CHAT_SERVICE = Symbol.for("posthog.core.agentChat.service");

/**
 * Incremental SSE→ACP mapper, implemented in the UI (`createAgentChatMapper`)
 * and handed to the service per chat. Stateful: a fresh one per session/stream.
 */
export interface AgentChatMapper {
  /** Optimistically render the user's just-sent message; the echoed frame is deduped. */
  seedUserMessage(text: string, ts?: number): AcpMessage[];
  /** Continue prompt-id numbering past `count` restored turns (resume). */
  setPromptIdBase(count: number): void;
  /** Translate one SSE event into zero or more ACP messages. */
  apply(event: AgentSessionEvent): AcpMessage[];
}

export type ClientToolCallData = Extract<
  AgentSessionEvent,
  { kind: "client_tool_call" }
>["data"];

/**
 * A client-tool result. `defer: true` means the host opened an interactive UI
 * and will post the outcome itself, so the service must not post one now.
 */
export interface ClientToolOutcome {
  result?: unknown;
  error?: string;
  defer?: boolean;
}

/**
 * Per-chat host seam supplied by the renderer hook. The transport saga lives in
 * the service; mapping, client-tool resolution, the context envelope, and local
 * history are UI concerns the service calls back into. Callbacks are expected to
 * be stable and read the latest handlers internally, so a long-lived stream
 * always sees current state.
 */
export interface AgentChatSession {
  /** Opaque key isolating this chat in the store. */
  chatId: string;
  /** Agent slug the chat targets. */
  agentSlug: string;
  ingressBaseUrl: string;
  /** Non-null routes this chat to a non-live revision (ingress JWT attached per call). */
  revisionId: string | null;
  /** `kind:'client'` tool ids this client can fulfil; sent to the runner at /run. */
  supportedClientTools?: readonly string[];
  createMapper(): AgentChatMapper;
  /** Resolve a client-tool call; `defer`/null ⇒ the service won't post a result. */
  resolveClientTool(
    data: ClientToolCallData,
  ): Promise<ClientToolOutcome | null>;
  /** Compose the wire text for a first message (prepends the context envelope). */
  buildWireText(text: string): string;
  /** Map a stored transcript to ACP messages (resume). */
  mapConversation(messages: AgentConversationMessage[]): AcpMessage[];
  /** Fired once a run starts, so the host can index local history. */
  onSessionStarted?(sessionId: string, text: string): void;
}
