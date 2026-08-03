import {
  ChatMarker,
  ChatMarkerContent,
  ChatMarkerIcon,
  cn,
  Spinner,
} from "@posthog/quill";
import { readAgentToolName } from "@posthog/shared";
import type { ToolCall } from "@posthog/ui/features/sessions/types";
import { memo } from "react";
import type { ConversationItem } from "../buildConversationItems";
import { grouping } from "../new-thread/conversationThreadConfig";
import { SessionUpdateView } from "../session-update/SessionUpdateView";
import { iconForToolCall } from "../session-update/toolCallUtils";

/** A contiguous run (≥2) of `tool_call` session-updates from one assistant turn. */
export type ToolGroupItem = {
  type: "tool_group";
  id: string;
  tools: Extract<ConversationItem, { type: "session_update" }>[];
};

/** Pull the resolved ToolCall + agent tool name from a `tool_call` session-update item. */
function resolveTool(item: ToolGroupItem["tools"][number]): {
  toolCall: ToolCall;
  toolName?: string;
} {
  const update = item.update as Extract<
    ConversationItem,
    { type: "session_update" }
  >["update"] & { toolCallId?: string };
  const mapped = update.toolCallId
    ? item.turnContext.toolCalls.get(update.toolCallId)
    : undefined;
  // A missing map entry means the tool is still in-flight (the resolved ToolCall is written when it
  // settles), so default its status to "in_progress" — otherwise the cast yields a status-less
  // ToolCall, `isToolActive` reads false, and the group label shows "Used …" mid-stream.
  const fromMap: ToolCall = mapped ?? {
    ...(update as unknown as ToolCall),
    status: (update as unknown as ToolCall).status ?? "in_progress",
  };
  return {
    toolCall: fromMap,
    toolName: readAgentToolName(fromMap._meta),
  };
}

/** Identity used to decide if a group is "all the same tool". */
function toolKey(item: ToolGroupItem["tools"][number]): string {
  const { toolCall, toolName } = resolveTool(item);
  return toolName ?? toolCall.kind ?? "tool";
}

/** Human label for a uniform group, e.g. `ToolSearch` → "Tool search", `mcp__x__run` → "Run". */
function friendlyName(key: string): string {
  if (grouping.subagentToolNames.has(key)) return "Subagents";
  const last = key.includes("__") ? (key.split("__").pop() ?? key) : key;
  // Split separators and PascalCase/camelCase so tool identifiers read naturally.
  const spaced = last
    .replace(/[_-]+/g, " ")
    .replace(/([a-z\d])([A-Z])/g, "$1 $2");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1).toLowerCase();
}

export function isToolActive(item: ToolGroupItem["tools"][number]): boolean {
  const { toolCall } = resolveTool(item);
  const incomplete =
    toolCall.status === "pending" || toolCall.status === "in_progress";
  return (
    incomplete &&
    !item.turnContext.turnCancelled &&
    !item.turnContext.turnComplete
  );
}

/**
 * Summary `ChatMarker` for a batch of consecutive tool calls. The trigger follows the most recent
 * call so a collapsed live turn still says exactly what the agent is doing: spinner, tool name,
 * short tool-provided context, and the `ChatMarker` chevron. The collapsible body holds each tool's
 * own marker via `SessionUpdateView` (which dispatches through `ToolCallBlock` → `ToolRow` →
 * `ChatMarker`). Tool groups always start collapsed, including while a turn is streaming.
 */
export const ToolGroup = memo(function ToolGroup({
  tools,
  mayStillGrow = false,
}: {
  tools: ToolGroupItem["tools"];
  /**
   * True when this run is the turn's trailing content and the turn is still
   * streaming — more tool calls may append to it. Keeps the label on "Using"
   * through the gaps between calls (every tool settled, next one not yet
   * issued), where the group's own status alone would flip it to "Used"
   * mid-turn and read as stalled.
   */
  mayStillGrow?: boolean;
}) {
  const isActive = tools.some(isToolActive) || mayStillGrow;

  const currentItem =
    [...tools].reverse().find(isToolActive) ?? tools[tools.length - 1];
  const current = resolveTool(currentItem);
  const currentName = friendlyName(toolKey(currentItem));
  const currentContext =
    current.toolCall.title &&
    current.toolCall.title.toLocaleLowerCase() !==
      currentName.toLocaleLowerCase()
      ? current.toolCall.title
      : null;
  const LeadIcon = iconForToolCall(current.toolCall, current.toolName);

  return (
    <ChatMarker
      defaultOpen={false}
      body={tools.map((item) => (
        <SessionUpdateView
          key={item.id}
          item={item.update}
          toolCalls={item.turnContext.toolCalls}
          childItems={item.turnContext.childItems}
          turnCancelled={item.turnContext.turnCancelled}
          turnComplete={item.turnContext.turnComplete}
          thoughtComplete={item.thoughtComplete}
        />
      ))}
      className="opacity-50 hover:opacity-100"
    >
      <ChatMarkerIcon>{isActive ? <Spinner /> : <LeadIcon />}</ChatMarkerIcon>
      <ChatMarkerContent
        className={cn(
          "flex min-w-0 items-center gap-1.5 text-muted-foreground text-sm",
          isActive && "shimmer",
        )}
      >
        <span className="shrink-0 font-medium">{currentName}</span>
        {currentContext ? (
          <span className="truncate text-muted-foreground/70">
            {currentContext}
          </span>
        ) : null}
      </ChatMarkerContent>
    </ChatMarker>
  );
});
