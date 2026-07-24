/**
 * Pure constructors for the JSON-RPC `AcpMessage` envelopes that code's
 * `buildConversationItems` reducer consumes.
 *
 * The agent_platform runtime speaks a different wire protocol (agent-ingress
 * SSE frames + a stored pi-ai `conversation` array). Rather than re-implement
 * the console's `runnerReducer`, we translate each agent_platform event into
 * the equivalent ACP message and let code's existing builder do all the
 * accumulation (streaming-text concatenation, tool-call merging, turn
 * tracking). These helpers mint those messages.
 *
 * Mapping summary:
 *   user message       → `session/prompt` request  → opens a turn + user bubble
 *   assistant text     → `session/update` (agent_message_chunk)
 *   assistant thinking → `session/update` (agent_thought_chunk)
 *   tool call          → `session/update` (tool_call)
 *   tool result        → `session/update` (tool_call_update)
 *   turn end           → `_posthog/turn_complete` notification
 */

import type {
  ContentBlock,
  SessionUpdate,
  ToolCallContent,
  ToolCallStatus,
} from "@agentclientprotocol/sdk";
import { POSTHOG_NOTIFICATIONS } from "@posthog/agent/acp-extensions";
import type { AcpMessage } from "@posthog/shared";

/** A plain-text ACP content block. */
export function textBlock(text: string): ContentBlock {
  return { type: "text", text };
}

/** A tool-call content item wrapping plain text (rendered under the call). */
export function textToolContent(text: string): ToolCallContent {
  return { type: "content", content: { type: "text", text } };
}

/**
 * A `session/prompt` JSON-RPC request. The builder keys a turn off the request
 * `id` and renders the prompt text as the user bubble, so each user message
 * needs a unique, monotonic id within the conversation.
 */
export function promptRequestMessage(
  id: number,
  text: string,
  ts: number,
): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      id,
      method: "session/prompt",
      params: { prompt: [textBlock(text)] },
    },
  };
}

/** A `session/update` notification wrapping an ACP `SessionUpdate`. */
export function sessionUpdateMessage(
  update: SessionUpdate,
  ts: number,
): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: { update },
    },
  };
}

/** A `_posthog/turn_complete` notification — closes the active turn. */
export function turnCompleteMessage(
  ts: number,
  stopReason?: string,
): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: POSTHOG_NOTIFICATIONS.TURN_COMPLETE,
      params: stopReason ? { stopReason } : {},
    },
  };
}

/** Streaming/settled assistant text fragment. */
export function agentTextUpdate(text: string): SessionUpdate {
  return { sessionUpdate: "agent_message_chunk", content: textBlock(text) };
}

/** Assistant thinking/reasoning fragment. */
export function agentThoughtUpdate(text: string): SessionUpdate {
  return { sessionUpdate: "agent_thought_chunk", content: textBlock(text) };
}

/**
 * A new tool call. Status is left to a later `tool_call_update` (from the
 * tool result) so a call without a result reads as still-running rather than
 * falsely completed.
 */
export function toolCallStartUpdate(
  toolCallId: string,
  title: string,
  rawInput?: unknown,
  status?: ToolCallStatus,
): SessionUpdate {
  return {
    sessionUpdate: "tool_call",
    toolCallId,
    title,
    ...(rawInput === undefined ? {} : { rawInput }),
    ...(status ? { status } : {}),
  };
}

/** Merge canonical args onto an existing tool call. */
export function toolCallArgsUpdate(
  toolCallId: string,
  title: string,
  rawInput: unknown,
): SessionUpdate {
  return { sessionUpdate: "tool_call_update", toolCallId, title, rawInput };
}

/** Finalize a tool call with its outcome (text body + completed/failed). */
export function toolResultUpdate(
  toolCallId: string,
  text: string,
  isError: boolean,
  rawOutput?: unknown,
): SessionUpdate {
  return {
    sessionUpdate: "tool_call_update",
    toolCallId,
    status: isError ? "failed" : "completed",
    content: [textToolContent(text)],
    ...(rawOutput === undefined ? {} : { rawOutput }),
  };
}
