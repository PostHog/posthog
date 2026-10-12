import { readAgentToolName } from "@posthog/shared";
import { hasUiAppResult } from "@posthog/ui/features/mcp-apps/hasUiAppResult";
import type {
  ConversationItem,
  TurnContext,
} from "@posthog/ui/features/sessions/components/buildConversationItems";
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

/**
 * Session-updates that `SessionUpdateView` always renders as `null`. They produce no row, so they
 * must not break a contiguous tool run.
 */
const INVISIBLE_UPDATES = new Set([
  "user_message_chunk",
  "tool_call_update",
  "plan",
  "available_commands_update",
  "config_option_update",
]);

/**
 * True when an item renders nothing, so it should be transparent to tool grouping. Besides the
 * always-null updates, this covers text chunks the stream emits with empty/whitespace or non-text
 * content (a stray empty `agent_message_chunk` between two tool calls is hidden via `empty:hidden`
 * but would otherwise split the run into two ungrouped markers).
 */
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

/**
 * A thought joins a tool run instead of breaking it, because between two calls it narrates the
 * stretch of work the run already stands for. The group's body still lists it in order. Prose to
 * the user (`agent_message_chunk`) does break a run, since that is addressed to the reader rather
 * than describing the work.
 */
function isThoughtItem(item: ConversationItem): boolean {
  return (
    item.type === "session_update" &&
    item.update.sessionUpdate === "agent_thought_chunk"
  );
}

function isTurnDecided(
  turnContext: TurnContext,
  erroredTurns: Set<TurnContext>,
  supersededTurns: Set<TurnContext>,
  isSessionIdle: boolean,
): boolean {
  // A cloud turn that errors out never gets a `turn_completed` event.
  if (erroredTurns.has(turnContext)) return true;
  if (!turnContext.turnComplete) return false;
  // `turnComplete` flips true the instant an implicit turn opens, so trust it only once
  // superseded or the session goes idle.
  return turnContext.isImplicit
    ? supersededTurns.has(turnContext) || isSessionIdle
    : true;
}

function lastRenderableIdsByTurn(
  items: ConversationItem[],
  isSessionIdle: boolean,
): Map<TurnContext, string> {
  const erroredTurns = new Set<TurnContext>();
  const lastIndexByTurn = new Map<TurnContext, number>();
  let lastSessionUpdateIndex = -1;
  items.forEach((item, index) => {
    if (!isSessionUpdateItem(item)) return;
    lastIndexByTurn.set(item.turnContext, index);
    lastSessionUpdateIndex = index;
    if (item.update.sessionUpdate === "error") {
      erroredTurns.add(item.turnContext);
    }
  });
  const supersededTurns = new Set<TurnContext>();
  for (const [turnContext, lastIndex] of lastIndexByTurn) {
    if (lastIndex < lastSessionUpdateIndex) supersededTurns.add(turnContext);
  }

  const out = new Map<TurnContext, string>();
  for (const item of items) {
    if (!isToolCallItem(item)) continue;
    if (
      !isTurnDecided(
        item.turnContext,
        erroredTurns,
        supersededTurns,
        isSessionIdle,
      )
    ) {
      continue;
    }
    if (!hasUiAppResult(item)) continue;
    out.set(item.turnContext, item.id);
  }
  return out;
}

/**
 * An item that must render as its own row, never folded into a `ToolGroupItem`:
 * a plan awaiting approval, a show-actions handoff, or a call whose result
 * carries a UI app. The next standalone item type joins this predicate instead
 * of widening the condition at the call site.
 *
 * A UI-app call cannot ride in a group, and `keepMounted` on the group body is
 * not the fix. It would keep every collapsed run's body mounted thread-wide,
 * and a chart inside a group still stays invisible until the user expands it:
 * while the run is live the group reads "Thinking…", so a rendered chart would
 * hide behind a collapsed panel. Keeping the chart outside the group is the
 * rule that fixes both.
 */
function rendersStandalone(
  item: ConversationItem,
  lastRenderableIds: Map<TurnContext, string>,
): boolean {
  const isPlanItem =
    item.type === "session_update" &&
    item.update.sessionUpdate === "tool_call" &&
    (item.update.kind === "switch_mode" ||
      isPlanApprovalTool(readAgentToolName(item.update._meta)));
  return (
    isPlanItem ||
    isShowActionsItem(item) ||
    (isToolCallItem(item) &&
      lastRenderableIds.get(item.turnContext) === item.id)
  );
}

/**
 * Collapse each contiguous run of ≥2 tool-call updates into a single `ToolGroupItem`. A run is
 * broken by any *visible* non-tool, non-thought item (prose, status) so groups follow reading
 * order; invisible updates (see {@link INVISIBLE_UPDATES}) are transparent and don't split a run.
 * A lone tool call passes through untouched as a single marker, and so do the thoughts around it:
 * thoughts ride along a run, they never make one. A standalone item (see
 * {@link rendersStandalone}) flushes the run and passes through alone.
 */
/**
 * Item arrays for settled runs, keyed on the run's (stable) first item.
 *
 * Grouping re-runs over the whole thread on every streamed chunk, so a completed run produces a
 * fresh array with identical contents each time. New identity defeats `ToolGroup`'s `memo`, which
 * makes every settled group above the live one re-render per chunk. Handing back the previous
 * array lets them skip the render.
 *
 * Only safe once the run's turn is complete, because a live tool's status is mutated in place on
 * its resolved `ToolCall`: reusing an array mid-turn would leave a spinner on a tool that has
 * since finished. `len` covers a run that gains items before it settles.
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

export function groupToolRuns(
  items: ConversationItem[],
  isPromptPending: boolean | null = true,
): ThreadItem[] {
  // `=== false` matches `incrementalConversationItems`'s own idle check.
  const lastRenderableIds = lastRenderableIdsByTurn(
    items,
    isPromptPending === false,
  );
  const out: ThreadItem[] = [];
  // The buffer holds the active run in order: tools, the thoughts between them, and any invisible
  // items interleaved with either.
  let buffer: ConversationItem[] = [];
  let toolCount = 0;

  const flush = () => {
    const hasEarlierRenderableCall = buffer.some(
      (item) =>
        isToolCallItem(item) &&
        hasUiAppResult(item) &&
        lastRenderableIds.get(item.turnContext) !== item.id,
    );
    if (toolCount >= 2 || hasEarlierRenderableCall) {
      out.push({
        type: "tool_group",
        // Keyed on the first tool call so the id survives thoughts appending around it.
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
      if (rendersStandalone(item, lastRenderableIds)) {
        flush();
        out.push(item);
        continue;
      }
      buffer.push(item);
      toolCount++;
    } else if (isInvisibleItem(item) || isThoughtItem(item)) {
      // Don't break the run; carry it along in order.
      buffer.push(item);
    } else {
      flush();
      out.push(item);
    }
  }
  flush();
  return out;
}
