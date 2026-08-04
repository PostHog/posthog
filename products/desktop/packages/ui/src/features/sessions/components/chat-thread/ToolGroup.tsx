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
import { summarize } from "../new-thread/buildThreadGroups";
import { grouping } from "../new-thread/conversationThreadConfig";
import { SessionUpdateView } from "../session-update/SessionUpdateView";
import { iconForToolCall } from "../session-update/toolCallUtils";

type SessionUpdateItem = Extract<ConversationItem, { type: "session_update" }>;

/** A contiguous run of one assistant turn's work: ≥2 `tool_call` updates plus the thoughts between them. */
export type ToolGroupItem = {
  type: "tool_group";
  id: string;
  /** Everything in the run, in order — what the body lists and what the summary counts. */
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

/** True while the run's last item is a thought still streaming — the agent is mid-reasoning. */
function isThinking(items: SessionUpdateItem[]): boolean {
  const last = items.at(-1);
  return (
    last?.update.sessionUpdate === "agent_thought_chunk" &&
    last.thoughtComplete === false
  );
}

/** Cross-fade between successive labels, so the row reads as one thing changing, not a new row. */
const LABEL_MOTION = {
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  exit: { opacity: 0 },
  transition: { duration: 0.18, ease: "easeOut" as const },
};

/**
 * One row standing in for a whole stretch of work: the tool calls and the thoughts between them.
 *
 * While it runs the row narrates — spinner plus whatever is happening right now (the current tool,
 * or "Thinking…" while the agent reasons between calls), cross-fading as that changes. Once the run
 * settles it collapses to what it did ("Ran 3 commands, read a file"), tallied by the same
 * `summarize` the legacy view uses. Opening it lists every step in order via `SessionUpdateView`.
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
  const thinking = isThinking(items);
  const isActive = tools.some(isToolActive) || thinking || mayStillGrow;

  // Grouping only ever builds a run around ≥2 tool calls, but the component is exported, so a
  // thought-only run resolves to no current tool rather than throwing on `undefined`.
  const currentItem =
    [...tools].reverse().find(isToolActive) ?? tools[tools.length - 1];
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

  // A settled run reads as a tally of what happened. One with nothing countable keeps the live
  // shape rather than falling back to summarize's "Worked". Memoized because the trailing group
  // re-renders per streamed token, and this walks the whole run.
  const summary = useMemo(() => summarize(items), [items]);
  const showSummary = !isActive && summary.hasCountableWork;

  // Keyed so a change swaps the label through the cross-fade. Thinking is its own key, so a run
  // that returns to the same tool after a thought still animates the change.
  const labelKey = showSummary
    ? `done:${summary.doneLabel}`
    : thinking || !currentName
      ? "thinking"
      : `tool:${currentName}:${currentContext ?? ""}`;

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
      // Matches ToolRow: aligned to the text column, no hover fill, inset ring,
      // and open looks the same as hover.
      className={cn(
        "mx-0 px-0 opacity-50 hover:bg-transparent hover:opacity-100 focus-visible:bg-transparent",
        "data-panel-open:bg-transparent data-panel-open:opacity-100",
        // The installed quill parks the chevron with `margin-inline-start: auto`;
        // unset it so it sits against the text it opens. Newer quill already
        // hugs, at which point this is inert.
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
        {/* `mode="wait"` so the outgoing label clears before the next fades in — overlapping them
            on one line reads as a flicker rather than a change. */}
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
            ) : thinking || !currentName ? (
              <span className="shrink-0 font-medium">Thinking…</span>
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
