import { readAgentToolName } from "@posthog/shared";
import { hasUiAppResult } from "@posthog/ui/features/mcp-apps/hasUiAppResult";
import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import type { ThreadItem } from "@posthog/ui/features/sessions/components/chat-thread/threadVirtualization";
import { isPlanApprovalTool } from "@posthog/ui/features/sessions/components/session-update/collaborationTools";
import { isShowActionsItem } from "@posthog/ui/features/sessions/components/session-update/showActionsItem";

type SessionUpdateItem = Extract<ConversationItem, { type: "session_update" }>;

function isToolCallItem(item: ConversationItem): item is SessionUpdateItem {
  return (
    item.type === "session_update" && item.update.sessionUpdate === "tool_call"
  );
}

function isSessionUpdateItem(
  item: ConversationItem,
): item is SessionUpdateItem {
  return item.type === "session_update";
}

/** These updates render no row, so they cannot split a continuous tool run. */
const INVISIBLE_UPDATES = new Set([
  "user_message_chunk",
  "tool_call_update",
  "plan",
  "available_commands_update",
  "config_option_update",
]);

/** Empty text chunks also render no row and must not split adjacent tool calls. */
function isInvisibleItem(item: ConversationItem): boolean {
  if (item.type !== "session_update") return false;
  const update = item.update;
  if (INVISIBLE_UPDATES.has(update.sessionUpdate)) return true;
  if (
    update.sessionUpdate === "agent_message_chunk" ||
    update.sessionUpdate === "agent_thought_chunk"
  ) {
    return update.content.type !== "text" || update.content.text.trim() === "";
  }
  return false;
}

/** A thought describes the surrounding work, so it stays inside that tool run. */
function isThoughtItem(item: ConversationItem): boolean {
  return (
    item.type === "session_update" &&
    item.update.sessionUpdate === "agent_thought_chunk"
  );
}

/** Plans, action buttons, and UI apps need a visible row outside a collapsed group. */
function rendersStandalone(item: ConversationItem): boolean {
  const isPlanItem =
    item.type === "session_update" &&
    item.update.sessionUpdate === "tool_call" &&
    (item.update.kind === "switch_mode" ||
      isPlanApprovalTool(readAgentToolName(item.update._meta)));
  return isPlanItem || isShowActionsItem(item) || hasUiAppResult(item);
}

/**
 * Reuse settled arrays so streamed updates do not render each completed group again.
 * Live arrays stay uncached because their tool status can change in place.
 */
const settledRunItems = new WeakMap<
  ConversationItem,
  { len: number; items: SessionUpdateItem[] }
>();

function stableRunItems(run: SessionUpdateItem[]): SessionUpdateItem[] {
  if (!run.at(-1)?.turnContext.turnComplete) return run;
  const key = run[0];
  const cached = settledRunItems.get(key);
  if (cached && cached.len === run.length) return cached.items;
  settledRunItems.set(key, { len: run.length, items: run });
  return run;
}

/** Collapse each continuous run with two or more tool calls into one group. */
export function groupToolRuns(items: ConversationItem[]): ThreadItem[] {
  const out: ThreadItem[] = [];
  let buffer: ConversationItem[] = [];
  let toolCount = 0;

  const flush = (): void => {
    if (toolCount >= 2) {
      out.push({
        type: "tool_group",
        id: buffer.filter(isToolCallItem)[0].id,
        items: stableRunItems(buffer.filter(isSessionUpdateItem)),
      });
    } else {
      out.push(...buffer);
    }
    buffer = [];
    toolCount = 0;
  };

  for (const item of items) {
    if (isToolCallItem(item)) {
      if (rendersStandalone(item)) {
        flush();
        out.push(item);
        continue;
      }
      buffer.push(item);
      toolCount++;
    } else if (isInvisibleItem(item) || isThoughtItem(item)) {
      buffer.push(item);
    } else {
      flush();
      out.push(item);
    }
  }
  flush();
  return out;
}
