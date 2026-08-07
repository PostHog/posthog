import type { AgentChatService } from "@posthog/core/agent-chat/agentChatService";
import { agentChatStore } from "@posthog/core/agent-chat/agentChatStore";
import {
  AGENT_CHAT_SERVICE,
  type AgentChatSession,
  type ClientToolCallData,
  type ClientToolOutcome,
} from "@posthog/core/agent-chat/identifiers";
import { useService } from "@posthog/di/react";
import type { DecideApprovalRequest } from "@posthog/shared/agent-platform-types";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { toast } from "@posthog/ui/primitives/toast";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { useStore } from "zustand";
import { useChatHistoryStore } from "../chat/chatHistoryStore";
import { buildConsoleContextEnvelope } from "../chat/consoleContext";
import { conversationToAcpMessages } from "../chat/conversationToAcp";
import { createAgentChatMapper } from "../chat/sessionEventToAcp";

export type { ClientToolOutcome };

/**
 * Resolves a client-tool call, or returns null to defer to the built-in
 * handlers (toast / get_context). Used by the agent builder to drive the UI
 * (focus_*) and the secret punch-out.
 */
export type ClientToolHandler = (
  data: ClientToolCallData,
) => ClientToolOutcome | null | Promise<ClientToolOutcome | null>;

export interface UseAgentChatOptions {
  /** Opaque key isolating this chat in the store (e.g. "agent-builder", "preview:<slug>"). */
  chatId: string;
  /** Agent slug the chat targets (drives client-tool context + history). */
  agentSlug: string;
  ingressBaseUrl: string | null;
  /**
   * When set, this chat routes to a specific non-live revision. The service
   * mints a short-lived ingress JWT scoped to that revision and attaches it on
   * every call; side effects still run for real. Leave null/unset to use the
   * agent's currently live revision.
   */
  revisionId?: string | null;
  /** Index started sessions in the local chat-history rail. */
  recordHistory?: boolean;
  /**
   * Supplies the "what am I looking at" object. When set, it's prepended as a
   * delimited envelope to the first message and answers the `get_context`
   * client tool. AgentBuilder only.
   */
  contextProvider?: () => unknown;
  /** AgentBuilder UI-driving tools (focus_*, set_secret); null → built-in handling. */
  clientTools?: ClientToolHandler;
  /**
   * `kind:'client'` tool ids this client can fulfil; sent to the runner at /run.
   * Pass a stable (module-level) array — it keys the session-config memo.
   */
  supportedClientTools?: readonly string[];
}

/**
 * Renderer entry point for a live chat against a deployed agent. Resolves the
 * core `AgentChatService` (which owns the transport saga and writes the
 * `agentChatStore`), supplies the authenticated client plus the UI seams
 * (mapper, client-tool resolution, context envelope, history), and exposes the
 * store-backed chat state and callbacks. Components read the chat by id and
 * render through `ConversationView`.
 */
export function useAgentChat({
  chatId,
  agentSlug,
  ingressBaseUrl,
  revisionId = null,
  recordHistory = false,
  contextProvider,
  clientTools,
  supportedClientTools,
}: UseAgentChatOptions) {
  const client = useAuthenticatedClient();
  const service = useService<AgentChatService>(AGENT_CHAT_SERVICE);
  const chat = useStore(agentChatStore, (s) => s.chats[chatId]);
  const recordChat = useChatHistoryStore((s) => s.record);

  // Latest provider/handler read at dispatch time without rebuilding the session.
  const contextProviderRef = useRef(contextProvider);
  contextProviderRef.current = contextProvider;
  const clientToolsRef = useRef(clientTools);
  clientToolsRef.current = clientTools;

  // Stable per-chat seam handed to the service. The callbacks read refs, so a
  // long-lived stream always sees the latest handler/provider.
  const session = useMemo<AgentChatSession>(
    () => ({
      chatId,
      agentSlug,
      ingressBaseUrl: ingressBaseUrl ?? "",
      revisionId,
      supportedClientTools,
      createMapper: createAgentChatMapper,
      resolveClientTool: (data) =>
        resolveClientTool(
          data,
          agentSlug,
          clientToolsRef.current,
          contextProviderRef.current,
        ),
      buildWireText: (text) => {
        const envelope = contextProviderRef.current?.();
        return envelope
          ? `${buildConsoleContextEnvelope(envelope)}\n\n${text}`
          : text;
      },
      mapConversation: conversationToAcpMessages,
      onSessionStarted: recordHistory
        ? (sessionId, text) =>
            recordChat(agentSlug, {
              sessionId,
              title: text.slice(0, 120),
              startedAt: Date.now(),
              revisionId: revisionId ?? undefined,
            })
        : undefined,
    }),
    [
      chatId,
      agentSlug,
      ingressBaseUrl,
      revisionId,
      supportedClientTools,
      recordHistory,
      recordChat,
    ],
  );

  const send = useCallback(
    (text: string): Promise<void> =>
      ingressBaseUrl ? service.send(client, session, text) : Promise.resolve(),
    [service, client, session, ingressBaseUrl],
  );

  const cancel = useCallback(
    () => service.cancel(client, session),
    [service, client, session],
  );

  const resume = useCallback(
    (sessionId: string): Promise<void> =>
      ingressBaseUrl
        ? service.resume(client, session, sessionId)
        : Promise.resolve(),
    [service, client, session, ingressBaseUrl],
  );

  // Decide a `principal`-type tool approval for this chat at the ingress (the
  // session owner clears their own gated call). The open stream resumes the
  // chat on approve.
  const decideApproval = useCallback(
    (approvalId: string, body: DecideApprovalRequest): Promise<void> =>
      ingressBaseUrl
        ? service.decideApproval(client, session, approvalId, body)
        : // No live session to decide against — reject (not a silent resolve) so
          // the card's mutation shows an error, not a false success toast.
          Promise.reject(
            new Error("This chat has no live session to decide the approval."),
          ),
    [service, client, session, ingressBaseUrl],
  );

  const resolveInteractiveTool = useCallback(
    (
      callId: string,
      outcome: { result: Record<string, unknown> } | { error: string },
    ): Promise<void> =>
      ingressBaseUrl
        ? service.resolveInteractiveTool(client, session, callId, outcome)
        : Promise.resolve(),
    [service, client, session, ingressBaseUrl],
  );

  const newChat = useCallback(
    () => service.newChat(session),
    [service, session],
  );

  // Release the open `/listen` socket when the consumer unmounts.
  useEffect(() => () => service.releaseStream(chatId), [service, chatId]);

  return {
    messages: chat?.messages ?? [],
    status: chat?.status ?? "idle",
    error: chat?.error ?? null,
    isStreaming: chat?.status === "streaming" || chat?.status === "starting",
    hasSession: !!chat?.sessionId,
    sessionId: chat?.sessionId ?? null,
    send,
    cancel,
    resume,
    newChat,
    resolveInteractiveTool,
    decideApproval,
  };
}

/**
 * Resolve a client-tool call: agent builder handler (focus_*, set_secret), then
 * `get_context` from the context provider, then the built-in toast / unhandled
 * fallback. Never resolves to null — `handleClientTool` is terminal.
 */
async function resolveClientTool(
  data: ClientToolCallData,
  agentSlug: string,
  clientTools: ClientToolHandler | undefined,
  contextProvider: (() => unknown) | undefined,
): Promise<ClientToolOutcome> {
  const handled = (await clientTools?.(data)) ?? null;
  if (handled) return handled;
  if (data.tool_id === "get_context") {
    return {
      result: contextProvider?.() ?? {
        agent: agentSlug,
        client: "posthog-code",
      },
    };
  }
  return handleClientTool(data, agentSlug);
}

/** Resolve a client-tool call. Immediate tools only; the rest degrade. */
function handleClientTool(
  data: ClientToolCallData,
  agentSlug: string,
): { result?: unknown; error?: string } {
  switch (data.tool_id) {
    case "toast": {
      const args = (data.args ?? {}) as { message?: string; level?: string };
      const message = args.message ?? "";
      if (args.level === "error") toast.error(message);
      else if (args.level === "warn") toast.warning(message);
      else toast.info(message);
      return { result: { shown: true } };
    }
    case "get_context":
      return { result: { agent: agentSlug, client: "posthog-code" } };
    default:
      // focus_*, set_secret, … land with the agent builder milestone.
      return { error: `unhandled_client_tool: ${data.tool_id}` };
  }
}
