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
   * Stable list key: the row's content-derived item id, so keys survive older-history prepends
   * and the end-anchored virtualizer holds the viewport. The optimistic->real swap of a just-sent
   * user message remounts its row, which this engine absorbs; the non-virtualized scroller cannot
   * (see {@link keyTurnRows}).
   */
  key: string;
  item: ThreadItem;
  /** True when this row belongs to an agent turn (turn-card padding + hover scope). */
  inTurn: boolean;
  /** Last row of its turn — a trailing tool group of a streaming turn may still grow. */
  isTrailingInTurn: boolean;
  /** Set on the last row of a completed turn; renders the turn's hover timestamp under it. */
  turnTimestamp?: number;
  /** Set alongside {@link turnTimestamp}: identifies the turn its footer actions act on. */
  turnId?: string;
  /** Set alongside {@link turnTimestamp}: the agent response as plain text, for its copy button. */
  turnCopyText?: string;
}

/**
 * Completion time of an agent turn, taken from its last session-update item (a tool group counts
 * by the last step in its run). Undefined while the turn is still streaming, since the timestamp
 * only appears once the whole turn is done.
 */
export function completedTurnTimestamp(turn: AgentTurn): number | undefined {
  for (let i = turn.items.length - 1; i >= 0; i--) {
    const item = turn.items[i];
    const last = item.type === "tool_group" ? item.items.at(-1) : item;
    if (last?.type !== "session_update") continue;
    return last.turnContext.turnComplete ? last.timestamp : undefined;
  }
  return undefined;
}

/** Viewport distance from the top of the loaded window that triggers an older-history page load. */
export const OLDER_HISTORY_LOAD_THRESHOLD_PX = 800;

export interface OlderHistoryLoadState {
  /** Whether reaching the threshold should still spend a page load. */
  armed: boolean;
  /** Whether to request a page now. */
  load: boolean;
}

/**
 * Whether the older-history loader fires, and what it is armed for next.
 *
 * One page per gesture, where the gesture is the viewport re-entering the threshold band. A load
 * that fails or comes back empty leaves the cursor where it was, so nothing re-arms the loader until
 * the reader scrolls back out and in — otherwise the arming timer would retry a failing request
 * every few hundred milliseconds for as long as the thread sat near the top.
 *
 * A window that does not fill the viewport is the one case with no gesture to wait for: it emits no
 * scroll events at all, so it stays armed and keeps paging until there is something to scroll. A
 * window that fills it but stays shorter than the band re-arms on reaching the bottom instead,
 * since `scrollTop` there can never clear the band.
 */
export function nextOlderHistoryLoadState(
  armed: boolean,
  input: {
    canLoad: boolean;
    isLoading: boolean;
    scrollTop: number;
    /** Largest `scrollTop` the viewport can reach; 0 when the window does not fill it. */
    maxScrollTop: number;
  },
): OlderHistoryLoadState {
  if (!input.canLoad) return { armed: false, load: false };
  if (input.scrollTop > OLDER_HISTORY_LOAD_THRESHOLD_PX) {
    return { armed: true, load: false };
  }
  if (input.isLoading) return { armed, load: false };
  if (input.maxScrollTop <= 0) return { armed: false, load: true };
  // A window shorter than the band never lets `scrollTop` clear it, so reaching the bottom is the
  // only gesture the reader has left. A landed page never leaves them there, so this cannot chain.
  if (input.scrollTop >= input.maxScrollTop) {
    return { armed: true, load: false };
  }
  if (!armed) return { armed, load: false };
  return { armed: false, load: true };
}

/** Flatten turn rows into the windowed row list (see {@link FlatThreadRow}). */
export function flattenTurnRows(rows: TurnRow[]): FlatThreadRow[] {
  const out: FlatThreadRow[] = [];
  for (const row of rows) {
    if (row.type === "agent_turn") {
      const timestamp = completedTurnTimestamp(row);
      const copyText =
        timestamp == null
          ? undefined
          : (buildTurnCopyText(row.items) ?? undefined);
      for (let i = 0; i < row.items.length; i++) {
        const item = row.items[i];
        const isTrailing = i === row.items.length - 1;
        out.push({
          key: item.id,
          item,
          inTurn: true,
          isTrailingInTurn: isTrailing,
          turnTimestamp: isTrailing ? timestamp : undefined,
          turnId: isTrailing ? row.id : undefined,
          turnCopyText: isTrailing ? copyText : undefined,
        });
      }
      continue;
    }
    out.push({
      key: row.id,
      item: row,
      inTurn: false,
      isTrailingInTurn: false,
    });
  }
  return out;
}

/** A top-level thread row paired with the list key the non-virtualized body renders it under. */
export interface KeyedTurnRow {
  key: string;
  item: TurnRow;
}

/** Key prefix per top-level row kind, or null for a kind turn grouping never emits as its own row. */
function turnRowKeyPrefix(row: TurnRow): string | null {
  switch (row.type) {
    case "user_message":
      return "user-turn";
    case "agent_turn":
      return "agent-turn";
    case "git_action":
      return "git-action";
    case "skill_button_action":
      return "skill-action";
    default:
      return null;
  }
}

/**
 * Assign list keys to the non-virtualized body's top-level rows.
 *
 * Every row is keyed by ordinal rather than by id, because a row's id moves while the row itself
 * stays in place. A user message and a skill-button action each swap an optimistic id for the real
 * one when the prompt echoes back, in the single commit that drops the optimistic item and appends
 * the event. An agent turn takes the id of its first item, and that item is replaced whenever tool
 * grouping reshapes the head of the turn: a turn that opens with a thought and then makes a second
 * tool call folds thought plus tools into one `tool_group`, so the turn's id moves from the thought
 * to the first tool call.
 *
 * Keying on those ids remounts the row. The scroller engine watches its content element for child
 * list changes, and a remount that neither adds nor removes a row reads to it as "the row count is
 * unchanged but here is a scroll-anchor element I have never scrolled to", which it answers by
 * scrolling that anchor to the top of the viewport. User messages are the anchors, so the thread
 * jumps to the oldest one the engine has not already scrolled to, which on the first such remount
 * is the start of the conversation.
 *
 * Rows are only ever appended here, so an ordinal is stable for the life of the row. A transcript
 * that can page older history renders windowed instead, precisely because a prepend would shift
 * every ordinal after it.
 */
export function keyTurnRows(rows: TurnRow[]): KeyedTurnRow[] {
  const ordinals = new Map<string, number>();
  return rows.map((item) => {
    const prefix = turnRowKeyPrefix(item);
    if (prefix === null) return { key: item.id, item };
    const ordinal = ordinals.get(prefix) ?? 0;
    ordinals.set(prefix, ordinal + 1);
    return { key: `${prefix}-${ordinal}`, item };
  });
}

/** Number of rows {@link flattenTurnRows} would produce, without building them. */
export function countFlatRows(rows: TurnRow[]): number {
  let count = 0;
  for (const row of rows) {
    count += row.type === "agent_turn" ? row.items.length : 1;
  }
  return count;
}

/**
 * Tolerance for calling the viewport "at the end". Generous because rows are estimated until they
 * mount and streamed content keeps appending, so the reader who has just scrolled down as far as
 * the wheel takes them is routinely tens of pixels short of the true bottom.
 */
export const THREAD_AT_END_THRESHOLD = 100;
/** Slack for sub-pixel scroll positions when deciding the viewport is hard against the bottom. */
export const THREAD_AT_EXACT_END_EPSILON = 1;
/** Movement below this is measurement noise, not a direction the reader chose. */
export const THREAD_SCROLL_DIRECTION_EPSILON = 1;
/**
 * A real upward drift, not a 1-frame measure transient: the DOM bottom sits this far below the
 * viewport. Well above any single append's measure gap.
 */
export const THREAD_FAR_DRIFT_THRESHOLD = 400;

/** Keys that move the viewport upward, so pressing them reads as leaving the end. */
export const SCROLL_UP_KEYS = new Set(["ArrowUp", "PageUp", "Home"]);

/** Whether a thread body re-pins to the bottom as content arrives. */
export interface ThreadFollowState {
  following: boolean;
  /**
   * The reader deliberately moved off the end. Held until they move back down into the end
   * tolerance, so streamed content that keeps growing under them never re-arms following on its
   * own — the reader's own downward gesture is what asks for it back.
   */
  leftEnd: boolean;
}

/** The follow state a thread starts in, and the one an explicit scroll-to-bottom restores. */
export const FOLLOWING_END: ThreadFollowState = {
  following: true,
  leftEnd: false,
};

/** A scroll event's geometry, as a thread body measures it. */
export interface ThreadScrollSample {
  /** Inside the at-end tolerance — a little above the bottom still counts, to absorb measure drift. */
  atEnd: boolean;
  /** Hard against the bottom, which always means following. */
  atExactEnd: boolean;
  /** The viewport moved upward since the previous sample. */
  scrolledUp: boolean;
  /** The viewport moved downward since the previous sample. */
  scrolledDown: boolean;
  /** Far enough below the fold that following is stuck mid-thread rather than measuring. */
  farFromEnd: boolean;
}

/** Measure one scroll position against the previous one. */
export function sampleThreadScroll(
  el: { scrollTop: number; scrollHeight: number; clientHeight: number },
  previousScrollTop: number,
): ThreadScrollSample {
  const distanceFromEnd = el.scrollHeight - el.clientHeight - el.scrollTop;
  const delta = el.scrollTop - previousScrollTop;
  return {
    atEnd: distanceFromEnd <= THREAD_AT_END_THRESHOLD,
    atExactEnd: distanceFromEnd <= THREAD_AT_EXACT_END_EPSILON,
    scrolledUp: delta < -THREAD_SCROLL_DIRECTION_EPSILON,
    scrolledDown: delta > THREAD_SCROLL_DIRECTION_EPSILON,
    farFromEnd: distanceFromEnd > THREAD_FAR_DRIFT_THRESHOLD,
  };
}

/** Fold one scroll sample into the follow state. */
export function nextThreadFollowState(
  state: ThreadFollowState,
  sample: ThreadScrollSample,
): ThreadFollowState {
  if (sample.atExactEnd) return FOLLOWING_END;
  // An upward move is intent even inside the tolerance, so a short gesture off the bottom isn't
  // undone by the scroll event it produced.
  if (sample.scrolledUp) return { following: false, leftEnd: state.leftEnd };
  if (state.leftEnd) {
    // Scrolling back down into the tolerance is the reader asking to follow again. Geometry alone
    // must not do it: streamed appends push the bottom away without the reader moving.
    return sample.atEnd && sample.scrolledDown ? FOLLOWING_END : state;
  }
  if (sample.atEnd) return FOLLOWING_END;
  if (sample.farFromEnd) return { following: false, leftEnd: false };
  return state;
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
