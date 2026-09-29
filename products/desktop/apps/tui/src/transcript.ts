import { convertStoredEntriesToEvents } from "@posthog/core/sessions/sessionEvents";
import {
  type AgentConversationEvent,
  type AgentRuntime,
  type StoredLogEntry,
  showActionSchema,
} from "@posthog/shared";
import {
  buildAgentConversationItems,
  buildConversationItems,
  type ConversationItem,
} from "@posthog/ui/features/sessions/components/buildConversationItems";
import { z } from "zod";

export type TranscriptLine =
  | { kind: "user"; id: string; text: string }
  | { kind: "assistant"; id: string; text: string }
  | { kind: "tool"; id: string; title: string; status: string }
  | { kind: "notice"; id: string; text: string; tone: "info" | "error" }
  | { kind: "actions"; id: string; actions: ShowAction[] };

export interface Transcript {
  lines: TranscriptLine[];
  // The agent is mid-turn: a prompt it has not finished answering.
  turnOpen: boolean;
}

// Pi runs log conversation events; ACP runs (Claude, Codex) log raw ACP notifications.
export function transcriptFrom(
  runtime: AgentRuntime | undefined,
  entries: StoredLogEntry[],
  taskDescription?: string,
): Transcript {
  const built =
    runtime === "pi"
      ? buildAgentConversationItems(
          entries.flatMap((entry): AgentConversationEvent[] =>
            entry.type === "pi_event" && entry.event ? [entry.event] : [],
          ),
          null,
        )
      : buildConversationItems(
          convertStoredEntriesToEvents(entries, taskDescription),
          null,
        );
  const lines = built.items.flatMap(toLine);
  const turnOpen = built.lastTurnInfo?.isComplete === false;
  // The sandbox echoes a new chat's first message only once it boots, so show it until then.
  if (
    runtime === "pi" &&
    taskDescription &&
    !lines.some((line) => line.kind === "user")
  ) {
    return {
      lines: [
        { kind: "user", id: "first-message", text: taskDescription },
        ...lines,
      ],
      turnOpen,
    };
  }
  return { lines, turnOpen };
}

// Bookkeeping the harness asks for every turn; it says nothing about the work.
const SUMMARY_TOOL = "task_summary_update";
// Buttons the agent offers; the desktop app draws them, and here the action picker does.
const ACTIONS_TOOL = "show_actions";
const actionsInput = z.object({ actions: z.array(showActionSchema).min(1) });
export type ShowAction = z.infer<typeof showActionSchema>;

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
      if (update.title.endsWith(SUMMARY_TOOL)) return [];
      if (update.title.endsWith(ACTIONS_TOOL)) {
        const input = actionsInput.safeParse(update.rawInput);
        return update.status !== "failed" && input.success
          ? [{ kind: "actions", id: item.id, actions: input.data.actions }]
          : [];
      }
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

// A message the user just sent shows at once, until the run's log echoes it back as its latest user message.
export function withPending(
  lines: TranscriptLine[],
  pending: string | null,
): TranscriptLine[] {
  if (!pending) return lines;
  const lastUser = lines.findLast((line) => line.kind === "user");
  if (lastUser?.kind === "user" && lastUser.text === pending) return lines;
  return [...lines, { kind: "user", id: "pending", text: pending }];
}
