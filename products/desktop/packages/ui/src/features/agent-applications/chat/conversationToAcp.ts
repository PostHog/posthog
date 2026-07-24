/**
 * Maps a stored agent_platform conversation transcript (the pi-ai
 * `conversation` array returned by the session-detail endpoint) into the
 * `AcpMessage[]` that code's `ConversationView` renders.
 *
 * Pure and order-preserving. Tool results arrive as their own `toolResult`
 * messages after the assistant turn that issued the call; we emit them as
 * `tool_call_update`s keyed by `toolCallId`, and the builder attaches them to
 * the matching call. Each `user` message opens a new turn, so we close the
 * previous one with a `_posthog/turn_complete` first (and once more at the
 * end) to bracket turns for duration/finalization.
 */

import type { AcpMessage } from "@posthog/shared";
import type {
  AgentAssistantContentPart,
  AgentConversationMessage,
  AgentUserContentPart,
} from "@posthog/shared/agent-platform-types";
import {
  agentTextUpdate,
  agentThoughtUpdate,
  promptRequestMessage,
  sessionUpdateMessage,
  toolCallStartUpdate,
  toolResultUpdate,
  turnCompleteMessage,
} from "./acpEnvelope";

/** Flatten a user message's content (string shorthand or text/image parts). */
export function userMessageText(
  content: string | AgentUserContentPart[],
): string {
  if (typeof content === "string") {
    return content;
  }
  return content
    .map((part) => (part.type === "text" ? part.text : ""))
    .join("");
}

/** Concatenate the text parts of a tool result's content. */
function toolResultText(content: { type: "text"; text: string }[]): string {
  return content.map((part) => part.text).join("");
}

function assistantPartToMessage(
  part: AgentAssistantContentPart,
  ts: number,
): AcpMessage | null {
  switch (part.type) {
    case "text":
      return sessionUpdateMessage(agentTextUpdate(part.text), ts);
    case "thinking":
      return sessionUpdateMessage(agentThoughtUpdate(part.thinking), ts);
    case "toolCall":
      return sessionUpdateMessage(
        toolCallStartUpdate(part.id, part.name, part.arguments),
        ts,
      );
    default:
      return null;
  }
}

export function conversationToAcpMessages(
  messages: AgentConversationMessage[],
): AcpMessage[] {
  const out: AcpMessage[] = [];
  let promptId = 0;
  let turnOpen = false;
  let lastTs = 0;

  for (const message of messages) {
    const ts = message.timestamp;
    lastTs = ts;

    if (message.role === "user") {
      // A new user prompt starts a new turn — close the prior one first.
      if (turnOpen) {
        out.push(turnCompleteMessage(ts));
        turnOpen = false;
      }
      promptId += 1;
      out.push(
        promptRequestMessage(promptId, userMessageText(message.content), ts),
      );
      turnOpen = true;
      continue;
    }

    if (message.role === "assistant") {
      for (const part of message.content) {
        const acp = assistantPartToMessage(part, ts);
        if (acp) {
          out.push(acp);
        }
      }
      continue;
    }

    // toolResult — finalize the matching tool call within the open turn.
    out.push(
      sessionUpdateMessage(
        toolResultUpdate(
          message.toolCallId,
          toolResultText(message.content),
          message.isError,
        ),
        ts,
      ),
    );
  }

  if (turnOpen) {
    out.push(turnCompleteMessage(lastTs));
  }
  return out;
}
