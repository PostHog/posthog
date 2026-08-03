import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import type { ToolGroupItem } from "@posthog/ui/features/sessions/components/chat-thread/ToolGroup";
import { buildTurnCopyText } from "@posthog/ui/features/sessions/components/chat-thread/turnCopyText";

/** A row is either a parsed conversation item or a synthesized group of tool calls. */
export type ThreadItem = ConversationItem | ToolGroupItem;

/**
 * A contiguous run of non-user rows (assistant prose, tools, git actions, ...) shown as one
 * block with tight internal spacing. Broken only by a user message.
 */
export type AgentTurn = {
  type: "agent_turn";
  id: string;
  items: ThreadItem[];
  /**
   * The user-initiated row that opened this turn — grouping emits it as a standalone row, so
   * without it "Copy turn" would carry the agent's prose but not the prompt it answers.
   */
  prompt?: ThreadItem;
};

/** Top-level row: a standalone user message, or a grouped agent turn. */
export type TurnRow = ThreadItem | AgentTurn;

/**
 * Flat-row count past which the thread switches to the windowed (virtualized) renderer.
 *
 * Counted in {@link FlatThreadRow}s, not turns or messages: a user message is one row, and an
 * agent turn contributes one row per item it holds (each prose block, each tool group, each git
 * action). A single exchange is therefore several rows — measured at roughly 5 on a
 * tool-heavy thread — so this number is well below the equivalent turn count.
 *
 * 250 comes from the prompts-per-task distribution (30 days, 9,458 tasks): p50 is 3 prompts, p90
 * is 17, p99 is 72, and the worst thread on record is 2,007. At ~5 rows per exchange, 250 rows is
 * ~50 prompts — the top 1.6% of threads, which carry 23% of all prompting. Lower thresholds
 * windowed a large share of ordinary conversations for no measured gain: at 51 rows both
 * renderers hold the same frame budget (p50 8.3ms, one dropped frame in 300), and upstream
 * MessageScroller documents the non-virtualized path as comfortable into the low thousands of
 * turns. Windowing is for the tail that actually degrades, not the median thread.
 *
 * Below it, every row stays mounted and the full quill scroller engine drives anchoring and
 * visibility — `content-visibility: auto` keeps paint cheap and the DOM small enough that React
 * commits stay fast. Past it, the unbounded DOM plus a full-thread reconcile per streamed chunk
 * is what locks the app, so the windowed renderer caps the mounted set instead. The switch is a
 * one-way ratchet per mounted thread: crossing the threshold flips once and never flips back,
 * so the two modes can't flap against each other mid-session.
 */
export const CHAT_THREAD_VIRTUALIZATION_THRESHOLD = 250;

/**
 * How far below the viewport top a user message may sit while still counting as the current
 * anchor — shared by the engine (`scrollPreviousItemPeek`) and the windowed sticky header.
 */
export const SCROLL_PREVIOUS_ITEM_PEEK = 64;

/**
 * Where the non-virtualized body was when the thread crossed the virtualization threshold, so the
 * windowed body can resume there. Recorded by row identity, not pixels: the two bodies don't share
 * a scroll coordinate space (virtual offsets are row-size estimates until rows mount).
 */
export interface ThreadScrollResume {
  atBottom: boolean;
  /** Id of the user message the engine was anchored to, or null if above the first one. */
  anchorId: string | null;
}

/**
 * One row of the virtualized thread. Agent turns are flattened to one row per item — a single
 * turn can contain thousands of tool calls (autonomous sessions), so windowing at turn
 * granularity would still mount an unbounded card. The turn's visual grouping survives via
 * per-row flags instead of a wrapper element.
 */
export interface FlatThreadRow {
  /**
   * Stable list key. User messages are keyed by ordinal so the optimistic->real id swap of a
   * just-sent message doesn't remount its row (same scheme as the non-virtualized path).
   */
  key: string;
  item: ThreadItem;
  /** True when this row belongs to an agent turn (turn-card padding + hover scope). */
  inTurn: boolean;
  /** Last row of its turn — a trailing tool group of a streaming turn may still grow. */
  isTrailingInTurn: boolean;
  /** Set on the last row of a completed turn; renders the turn's hover timestamp under it. */
  turnTimestamp?: number;
  /** Set alongside {@link turnTimestamp}: the whole turn as plain text, for its copy button. */
  turnCopyText?: string;
}

/**
 * Completion time of an agent turn, taken from its last session-update item (tool groups count
 * by their last tool). Undefined while the turn is still streaming — the timestamp only appears
 * once the whole turn is done.
 */
export function completedTurnTimestamp(turn: AgentTurn): number | undefined {
  for (let i = turn.items.length - 1; i >= 0; i--) {
    const item = turn.items[i];
    const last = item.type === "tool_group" ? item.tools.at(-1) : item;
    if (last?.type !== "session_update") continue;
    return last.turnContext.turnComplete ? last.timestamp : undefined;
  }
  return undefined;
}

/** Flatten turn rows into the windowed row list (see {@link FlatThreadRow}). */
export function flattenTurnRows(rows: TurnRow[]): FlatThreadRow[] {
  const out: FlatThreadRow[] = [];
  let userTurn = 0;
  for (const row of rows) {
    if (row.type === "agent_turn") {
      const timestamp = completedTurnTimestamp(row);
      const copyText =
        timestamp == null
          ? undefined
          : (buildTurnCopyText(
              row.prompt ? [row.prompt, ...row.items] : row.items,
            ) ?? undefined);
      for (let i = 0; i < row.items.length; i++) {
        const item = row.items[i];
        const isTrailing = i === row.items.length - 1;
        out.push({
          key: item.id,
          item,
          inTurn: true,
          isTrailingInTurn: isTrailing,
          turnTimestamp: isTrailing ? timestamp : undefined,
          turnCopyText: isTrailing ? copyText : undefined,
        });
      }
      continue;
    }
    out.push({
      key: row.type === "user_message" ? `user-turn-${userTurn++}` : row.id,
      item: row,
      inTurn: false,
      isTrailingInTurn: false,
    });
  }
  return out;
}

/** Number of rows {@link flattenTurnRows} would produce, without building them. */
export function countFlatRows(rows: TurnRow[]): number {
  let count = 0;
  for (const row of rows) {
    count += row.type === "agent_turn" ? row.items.length : 1;
  }
  return count;
}

/** A user-message row's measured extent in the scroll space, in row order. */
export interface StickyAnchorEntry {
  id: string;
  /** Row top offset within the scroll space. */
  start: number;
  /** Row bottom offset within the scroll space. */
  end: number;
}

export interface StickyAnchorState {
  anchorId: string | null;
}

/**
 * The user message anchoring the current viewport: the last user row whose top sits at or above
 * the viewport top plus `peek` — the same band the scroller engine's anchor scan uses in the
 * non-virtualized thread.
 */
export function computeStickyAnchor(
  entries: readonly StickyAnchorEntry[],
  scrollTop: number,
  peek: number,
): StickyAnchorState {
  let anchor: StickyAnchorEntry | null = null;
  for (const entry of entries) {
    if (entry.start <= scrollTop + peek) {
      anchor = entry;
    } else {
      break;
    }
  }
  return { anchorId: anchor?.id ?? null };
}
