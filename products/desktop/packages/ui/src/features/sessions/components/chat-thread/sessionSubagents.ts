import { readAgentToolName } from "@posthog/shared";
import type {
  ConversationItem,
  TurnContext,
} from "@posthog/ui/features/sessions/components/buildConversationItems";
import type { TurnRow } from "@posthog/ui/features/sessions/components/chat-thread/threadVirtualization";
import { isSubagentSpawnTool } from "@posthog/ui/features/sessions/components/session-update/collaborationTools";
import {
  compactOrchestrationText,
  readPiOrchestrationDetails,
} from "@posthog/ui/features/sessions/components/session-update/piOrchestrationDetails";
import { getContentText } from "@posthog/ui/features/sessions/components/session-update/toolCallUtils";
import type { ToolCall } from "@posthog/ui/features/sessions/types";
import type { StepStatus } from "@posthog/ui/primitives/StepList";

export interface SessionSubagent {
  key: string;
  /** Id of the tool call item that spawned the subagent: the place in the thread to jump to. */
  itemId: string;
  label: string;
  /** `pending` means the subagent stopped before it finished, because its turn ended. */
  status: StepStatus;
  currentTool?: string;
  result?: string;
}

type SessionUpdateItem = Extract<ConversationItem, { type: "session_update" }>;

/** A run that still reads as live after its turn ended will never finish, so it reads as stopped. */
function settleStatus(status: StepStatus, turn: TurnContext): StepStatus {
  if (status !== "in_progress") return status;
  return turn.turnComplete || turn.turnCancelled ? "pending" : status;
}

function readToolCallStatus(toolCall: ToolCall): StepStatus {
  if (toolCall.status === "completed") return "completed";
  if (toolCall.status === "failed") return "failed";
  return "in_progress";
}

function lastChildToolTitle(children: ConversationItem[] | undefined) {
  if (!children) return undefined;
  for (let i = children.length - 1; i >= 0; i--) {
    const child = children[i];
    if (
      child.type === "session_update" &&
      child.update.sessionUpdate === "tool_call" &&
      child.update.title
    ) {
      return child.update.title;
    }
  }
  return undefined;
}

function compactResult(text: string | undefined): string | undefined {
  const compacted = text ? compactOrchestrationText(text) : "";
  return compacted || undefined;
}

function collectFromItem(item: SessionUpdateItem, out: SessionSubagent[]) {
  const update = item.update;
  if (update.sessionUpdate !== "tool_call" || !update.toolCallId) return;
  const turn = item.turnContext;
  const toolCall =
    turn.toolCalls.get(update.toolCallId) ?? (update as unknown as ToolCall);

  const view = readPiOrchestrationDetails(toolCall.title, toolCall.details);
  if (view?.kind === "subagent") {
    for (const run of view.agentRuns) {
      out.push({
        key: `${item.id}:${run.key}`,
        itemId: item.id,
        label: run.description || run.agent,
        status: settleStatus(run.status, turn),
        currentTool: run.toolCalls.at(-1)?.title,
        result: compactResult(run.errorMessage ?? run.resultText),
      });
    }
    return;
  }

  const toolName = readAgentToolName(update._meta) ?? update.title;
  if (!isSubagentSpawnTool(toolName)) return;
  const status = settleStatus(readToolCallStatus(toolCall), turn);
  out.push({
    key: item.id,
    itemId: item.id,
    label: toolCall.title || "Subagent",
    status,
    currentTool: lastChildToolTitle(turn.childItems.get(update.toolCallId)),
    result:
      status === "completed" || status === "failed"
        ? compactResult(getContentText(toolCall.content))
        : undefined,
  });
}

/**
 * Every subagent the session spawned, in thread order. Reads the same sources the thread rows
 * render from: Pi subagent `results` details, and Task/Agent calls with their child items.
 */
export function collectSessionSubagents(
  items: ConversationItem[],
): SessionSubagent[] {
  const out: SessionSubagent[] = [];
  for (const item of items) {
    if (item.type === "session_update") collectFromItem(item, out);
  }
  return out;
}

/**
 * The rows that hold an item. The plain thread body registers one scroll target per agent turn,
 * and the windowed body one per thread item (a tool group counts as one item), so a jump needs
 * both ids.
 */
export function findItemRow(
  rows: TurnRow[],
  itemId: string,
): { turnId: string; rowId: string } | undefined {
  for (const row of rows) {
    const threadItems = row.type === "agent_turn" ? row.items : [row];
    for (const threadItem of threadItems) {
      const members =
        threadItem.type === "tool_group" ? threadItem.items : [threadItem];
      if (members.some((member) => member.id === itemId)) {
        return { turnId: row.id, rowId: threadItem.id };
      }
    }
  }
  return undefined;
}
