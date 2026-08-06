import {
  ChatMarker,
  ChatMarkerContent,
  ChatMarkerIcon,
  cn,
  Spinner,
} from "@posthog/quill";
import { readAgentToolName } from "@posthog/shared";
import type { ToolCall } from "@posthog/ui/features/sessions/types";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { memo, useMemo } from "react";
import type { ConversationItem } from "../buildConversationItems";
import { summarizeMemo } from "../new-thread/buildThreadGroups";
import { grouping } from "../new-thread/conversationThreadConfig";
import { SessionUpdateView } from "../session-update/SessionUpdateView";
import { iconForToolCall } from "../session-update/toolCallUtils";

type SessionUpdateItem = Extract<ConversationItem, { type: "session_update" }>;

/** A contiguous run of at least two `tool_call` updates. */
export type ToolGroupItem = {
  type: "tool_group";
  id: string;
  /** Every tool call in the run, in order. */
  items: SessionUpdateItem[];
};

/** Pull the resolved ToolCall + agent tool name from a `tool_call` session-update item. */
function resolveTool(item: SessionUpdateItem): {
  toolCall: ToolCall;
  toolName?: string;
} {
  const update = item.update as SessionUpdateItem["update"] & {
    toolCallId?: string;
  };
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
function toolKey(item: SessionUpdateItem): string {
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

export function isToolActive(item: SessionUpdateItem): boolean {
  const { toolCall } = resolveTool(item);
  const incomplete =
    toolCall.status === "pending" || toolCall.status === "in_progress";
  return (
    incomplete &&
    !item.turnContext.turnCancelled &&
    !item.turnContext.turnComplete
  );
}

/** The run's most recent in-flight tool. Walked backwards rather than copy-and-reverse. */
function lastActiveTool(
  tools: SessionUpdateItem[],
): SessionUpdateItem | undefined {
  for (let i = tools.length - 1; i >= 0; i--) {
    if (isToolActive(tools[i])) return tools[i];
  }
  return undefined;
}

/** Cross-fade between successive labels, so the row reads as one thing changing, not a new row. */
const LABEL_MOTION = {
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  exit: { opacity: 0 },
  transition: { duration: 0.18, ease: "easeOut" as const },
};

/**
 * One row standing in for a contiguous stretch of tool calls. While the run is live, the row
 * shows the current tool. Once it settles, the row summarizes the completed work.
 */
export const ToolGroup = memo(function ToolGroup({
  items,
  mayStillGrow = false,
}: {
  items: SessionUpdateItem[];
  /**
   * True when this run is the turn's trailing content and the turn is still
   * streaming — more tool calls may append to it. Keeps the label live through
   * the gaps between calls (every tool settled, next one not yet issued), where
   * the group's own status alone would flip it to the done summary mid-turn and
   * read as stalled.
   */
  mayStillGrow?: boolean;
}) {
  const reduceMotion = useReducedMotion();
  // Derived, not passed: two arrays that have to agree can stop agreeing.
  const tools = useMemo(
    () => items.filter((item) => item.update.sessionUpdate === "tool_call"),
    [items],
  );
  const isActive = tools.some(isToolActive) || mayStillGrow;

  const currentItem = lastActiveTool(tools) ?? tools.at(-1);
  const current = currentItem ? resolveTool(currentItem) : null;
  const currentName = currentItem ? friendlyName(toolKey(currentItem)) : null;
  const currentContext =
    current?.toolCall.title &&
    currentName &&
    current.toolCall.title.toLocaleLowerCase() !==
      currentName.toLocaleLowerCase()
      ? current.toolCall.title
      : null;
  const LeadIcon = current
    ? iconForToolCall(current.toolCall, current.toolName)
    : null;

  // Cached once the turn completes because the walk is O(run) and the live turn re-renders every
  // group on every streamed chunk.
  const summary = useMemo(
    () => summarizeMemo(items, items.at(-1)?.turnContext.turnComplete ?? false),
    [items],
  );
  const showSummary = !isActive && summary.hasCountableWork;

  const labelKey = showSummary
    ? `done:${summary.doneLabel}`
    : `tool:${currentName ?? "working"}:${currentContext ?? ""}`;

  return (
    <ChatMarker
      defaultOpen={false}
      body={items.map((item) => (
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
      // Same row chrome as ToolRow; see the comment there for why quill's
      // defaults are overridden.
      className={cn(
        "mx-0 px-0 opacity-50 hover:bg-transparent hover:opacity-100 focus-visible:bg-transparent",
        "data-panel-open:bg-transparent data-panel-open:opacity-100",
        "[&>svg:last-child]:ms-0",
        "focus-visible:shadow-none focus-visible:ring-(--ring)/50 focus-visible:ring-2 focus-visible:ring-inset",
      )}
    >
      <ChatMarkerIcon>
        {isActive || !LeadIcon ? <Spinner /> : <LeadIcon />}
      </ChatMarkerIcon>
      <ChatMarkerContent
        className={cn(
          "flex min-w-0 items-center gap-1.5 overflow-hidden text-muted-foreground text-sm",
          isActive && "shimmer",
        )}
      >
        {/* `mode="wait"` so the outgoing label clears before the next fades in. Overlapping them
            on a single line reads as a flicker rather than a change. */}
        <AnimatePresence mode="wait" initial={false}>
          <motion.span
            key={labelKey}
            className="flex min-w-0 items-center gap-1.5"
            initial={reduceMotion ? false : LABEL_MOTION.initial}
            animate={reduceMotion ? undefined : LABEL_MOTION.animate}
            exit={reduceMotion ? undefined : LABEL_MOTION.exit}
            transition={reduceMotion ? undefined : LABEL_MOTION.transition}
          >
            {showSummary ? (
              <span className="truncate">{summary.doneLabel}</span>
            ) : (
              <>
                <span className="shrink-0 font-medium">{currentName}</span>
                {currentContext ? (
                  <span className="truncate text-muted-foreground/70">
                    {currentContext}
                  </span>
                ) : null}
              </>
            )}
          </motion.span>
        </AnimatePresence>
      </ChatMarkerContent>
    </ChatMarker>
  );
});
