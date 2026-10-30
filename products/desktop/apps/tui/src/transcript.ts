import { convertStoredEntriesToEvents } from "@posthog/core/sessions/sessionEvents";
import type {
  AgentConversationEvent,
  AgentRuntime,
  StoredLogEntry,
} from "@posthog/shared";
import {
  buildAgentConversationItems,
  buildConversationItems,
  type ConversationItem,
} from "@posthog/ui/features/sessions/components/buildConversationItems";

export type TranscriptLine =
  | { kind: "user"; id: string; text: string }
  | { kind: "assistant"; id: string; text: string }
  | { kind: "tool"; id: string; title: string; status: string }
  | { kind: "notice"; id: string; text: string; tone: "info" | "error" };

// Pi runs log conversation events; ACP runs (Claude, Codex) log raw ACP notifications.
export function transcriptFrom(
  runtime: AgentRuntime | undefined,
  entries: StoredLogEntry[],
  taskDescription?: string,
): TranscriptLine[] {
  const items =
    runtime === "pi"
      ? buildAgentConversationItems(
          entries.flatMap((entry): AgentConversationEvent[] =>
            entry.type === "pi_event" && entry.event ? [entry.event] : [],
          ),
          null,
        ).items
      : buildConversationItems(
          convertStoredEntriesToEvents(entries, taskDescription),
          null,
        ).items;
  return items.flatMap(toLine);
}

function toLine(item: ConversationItem): TranscriptLine[] {
  if (item.type === "user_message") {
    return [{ kind: "user", id: item.id, text: item.content }];
  }
  if (item.type === "turn_cancelled") {
    return [{ kind: "notice", id: item.id, text: "Cancelled", tone: "info" }];
  }
  if (item.type !== "session_update") return [];
  const update = item.update;
  switch (update.sessionUpdate) {
    case "agent_message_chunk":
      return update.content.type === "text"
        ? [{ kind: "assistant", id: item.id, text: update.content.text }]
        : [];
    case "tool_call":
      return [
        {
          kind: "tool",
          id: item.id,
          title: update.title,
          status: update.status ?? "pending",
        },
      ];
    case "status":
      return update.error
        ? [{ kind: "notice", id: item.id, text: update.error, tone: "error" }]
        : [];
    default:
      return [];
  }
}
