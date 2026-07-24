/**
 * Maps the live agent-ingress SSE stream (`AgentSessionEvent`) into the
 * `AcpMessage[]` code's `ConversationView` renders, incrementally.
 *
 * Stateful by necessity: user messages need monotonic JSON-RPC request ids,
 * and tool-call lifecycle events arrive by id and must be distinguished
 * between "first sighting" (emit a `tool_call`) and "follow-up" (emit a
 * `tool_call_update` the builder merges). A fresh mapper is created per
 * session/stream.
 *
 * As with the stored-transcript mapper, code's `buildConversationItems` does
 * all the accumulation — this only translates the wire shape. Streaming
 * tool-call arg deltas (`tool_call_args_delta`) are intentionally dropped:
 * the canonical `tool_call` event carries the full args a beat later, and
 * rendering half-streamed JSON as `rawInput` reads worse than a brief gap.
 */

import type { AgentChatMapper } from "@posthog/core/agent-chat/identifiers";
import type { AcpMessage } from "@posthog/shared";
import type { AgentSessionEvent } from "@posthog/shared/agent-platform-types";
import {
  agentTextUpdate,
  agentThoughtUpdate,
  promptRequestMessage,
  sessionUpdateMessage,
  toolCallArgsUpdate,
  toolCallStartUpdate,
  toolResultUpdate,
  turnCompleteMessage,
} from "./acpEnvelope";
import { stripConsoleContext } from "./consoleContext";

function toEpochMs(iso: string): number {
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? 0 : ms;
}

/** Render a tool result's `output`/`error` payload as display text. */
function outputText(value: unknown): string {
  if (value == null) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export type { AgentChatMapper };

export function createAgentChatMapper(): AgentChatMapper {
  let promptId = 0;
  const seenToolCalls = new Set<string>();
  // Texts shown optimistically and awaiting their echoed `user_message` frame.
  // Compared by trimmed form so runner-side whitespace normalization
  // (trailing `\n`, padding around envelopes, etc.) doesn't break dedup.
  const pendingOptimistic: string[] = [];
  // Every user text we've rendered this session, normalized. Catches the runner
  // re-emitting the same `user_message` event twice (the second arrival has
  // nothing left in `pendingOptimistic` to swallow it).
  const seenUserTexts = new Set<string>();

  return {
    seedUserMessage(text: string, ts?: number): AcpMessage[] {
      if (!text) {
        return [];
      }
      promptId += 1;
      pendingOptimistic.push(text);
      seenUserTexts.add(text.trim());
      return [promptRequestMessage(promptId, text, ts ?? Date.now())];
    },

    setPromptIdBase(count: number): void {
      promptId = Math.max(promptId, count);
    },

    apply(event: AgentSessionEvent): AcpMessage[] {
      const ts = toEpochMs(event.ts);

      switch (event.kind) {
        case "user_message": {
          if (!event.data.text) {
            return [];
          }
          // The first message may carry a agent builder context envelope — strip it
          // so it never shows in the transcript (and so dedup matches the clean
          // optimistic text the composer rendered).
          const text = stripConsoleContext(event.data.text);
          const normalized = text.trim();
          // Echo of a message we already rendered optimistically. Scan the
          // queue (not just `[0]`) so out-of-order echoes from rapid sends
          // still match, and compare trimmed forms so trailing/leading
          // whitespace from the runner doesn't break the match.
          const pendingIdx = pendingOptimistic.findIndex(
            (p) => p.trim() === normalized,
          );
          if (pendingIdx !== -1) {
            pendingOptimistic.splice(pendingIdx, 1);
            return [];
          }
          // The runner re-emitted a `user_message` we've already rendered
          // (either as optimistic seed or as a non-dedup'd echo). Drop it so
          // the bubble doesn't appear twice.
          if (seenUserTexts.has(normalized)) {
            return [];
          }
          seenUserTexts.add(normalized);
          promptId += 1;
          return [promptRequestMessage(promptId, text, ts)];
        }

        case "assistant_text_delta":
          return event.data.text
            ? [sessionUpdateMessage(agentTextUpdate(event.data.text), ts)]
            : [];

        case "assistant_thinking_delta":
          return event.data.thinking
            ? [
                sessionUpdateMessage(
                  agentThoughtUpdate(event.data.thinking),
                  ts,
                ),
              ]
            : [];

        case "tool_call_start": {
          const { id, name } = event.data;
          if (seenToolCalls.has(id)) {
            return [];
          }
          seenToolCalls.add(id);
          return [
            sessionUpdateMessage(
              toolCallStartUpdate(id, name, undefined, "in_progress"),
              ts,
            ),
          ];
        }

        case "tool_call": {
          const { id, name, args } = event.data;
          if (seenToolCalls.has(id)) {
            return [
              sessionUpdateMessage(
                toolCallArgsUpdate(id, name, args ?? {}),
                ts,
              ),
            ];
          }
          seenToolCalls.add(id);
          return [
            sessionUpdateMessage(
              toolCallStartUpdate(id, name, args ?? {}, "in_progress"),
              ts,
            ),
          ];
        }

        case "tool_result": {
          const { id, ok, output, error, tool } = event.data;
          const isError = ok === false;
          const text = isError ? (error ?? "tool failed") : outputText(output);
          const messages: AcpMessage[] = [];
          // Defensive: a result for a call we never saw start — synthesize the
          // call so the builder has something to attach the result to.
          if (!seenToolCalls.has(id)) {
            seenToolCalls.add(id);
            messages.push(
              sessionUpdateMessage(toolCallStartUpdate(id, tool ?? "tool"), ts),
            );
          }
          messages.push(
            sessionUpdateMessage(
              toolResultUpdate(id, text, isError, output),
              ts,
            ),
          );
          return messages;
        }

        case "client_tool_result": {
          const { call_id, result, error } = event.data;
          const isError = typeof error === "string";
          const text = isError
            ? (error ?? "client tool failed")
            : outputText(result);
          return [
            sessionUpdateMessage(
              toolResultUpdate(call_id, text, isError, result),
              ts,
            ),
          ];
        }

        case "completed":
          return [turnCompleteMessage(ts)];

        case "waiting":
          return [turnCompleteMessage(ts)];

        case "failed":
          return [turnCompleteMessage(ts, "failed")];

        // Frames that carry no renderable transcript content. `turn_started`
        // is implicit in the prompt request; `assistant_text` is a turn-end
        // snapshot the deltas already produced; `tool_call_args_delta` is
        // dropped (see file header); `client_tool_call` is handled by the
        // host transport (M4); the rest are lifecycle bookkeeping.
        default:
          return [];
      }
    },
  };
}

/** Fold a full event buffer through a fresh mapper — handy for replay/tests. */
export function sessionEventsToAcpMessages(
  events: AgentSessionEvent[],
): AcpMessage[] {
  const mapper = createAgentChatMapper();
  return events.flatMap((event) => mapper.apply(event));
}
