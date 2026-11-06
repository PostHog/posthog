import {
  ChatMessageScroller,
  ChatMessageScrollerButton,
  ChatMessageScrollerContent,
  ChatMessageScrollerViewport,
} from "@posthog/quill";
import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { MessageMinimap } from "@posthog/ui/features/sessions/components/chat-thread/MessageMinimap";
import {
  computeStickyAnchor,
  type FlatThreadRow,
  FOLLOWING_END,
  nextOlderHistoryLoadState,
  nextThreadFollowState,
  SCROLL_PREVIOUS_ITEM_PEEK,
  SCROLL_UP_KEYS,
  type StickyAnchorEntry,
  type StickyAnchorState,
  sampleThreadScroll,
  THREAD_AT_END_THRESHOLD,
  type ThreadFollowState,
  type ThreadScrollResume,
} from "@posthog/ui/features/sessions/components/chat-thread/threadVirtualization";
import {
  CHAT_CONTENT_MAX_WIDTH,
  CHAT_CONTENT_PADDING_INLINE,
} from "@posthog/ui/features/sessions/constants";
import { useVirtualizer, type Virtualizer } from "@tanstack/react-virtual";
import {
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
  type WheelEvent as ReactWheelEvent,
  type RefObject,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

// Windowing geometry. Estimate/overscan/drift values match the legacy VirtualizedList, whose
// tuning these rows share (same item mix, same measure-then-settle churn).
const ESTIMATED_ROW_SIZE = 80;
const OVERSCAN = 12;
/** Top of the virtual coordinate space — stands in for the non-virtualized content's `py-4`. */
const PADDING_START = 16;
/** Frames a programmatic scroll keeps re-issuing while rows around the target still measure. */
const SETTLE_AT_END_ATTEMPTS = 12;
const SETTLE_TO_INDEX_ATTEMPTS = 8;

type ThreadVirtualizer = Virtualizer<HTMLDivElement, Element>;

/** A user message's position in the flat row list, used to derive the sticky-header anchor. */
interface UserRow {
  id: string;
  index: number;
}

/**
 * Reserves the footer's height as virtual `paddingEnd` rather than rendering it as a virtual row:
 * a footer row's key would be constant and always last, which permanently kills tanstack's
 * `followOnAppend` (it only fires when the last virtual key changes). With the footer out of the
 * count the last virtual item is the real last message, and the virtual end still lines up with
 * the real DOM bottom.
 */
function useReservedFooterHeight(
  footerRef: RefObject<HTMLDivElement | null>,
  hasFooter: boolean,
): number {
  const [footerHeight, setFooterHeight] = useState(0);
  useLayoutEffect(() => {
    const el = footerRef.current;
    const measure = () => {
      const height = hasFooter && el ? el.offsetHeight : 0;
      setFooterHeight((prev) => (prev === height ? prev : height));
    };
    measure();
    if (!hasFooter || !el) return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [hasFooter, footerRef]);
  return footerHeight;
}

/**
 * Programmatic scrolls that survive measurement drift. Rows are estimated until they mount, so a
 * single `scrollToEnd`/`scrollToIndex` lands short; both helpers re-issue across frames until the
 * target offset stops moving. `followRef` is the follow state the rest of the body reads.
 */
function useSettleControls(
  virtualizer: ThreadVirtualizer,
  viewportRef: RefObject<HTMLDivElement | null>,
) {
  // Starts following; the mount-position effect below flips it if the handoff state says the reader
  // was parked above the fold.
  const followRef = useRef<ThreadFollowState>(FOLLOWING_END);
  const settleRafRef = useRef<number | null>(null);

  const cancelSettle = useCallback(() => {
    if (settleRafRef.current !== null) {
      cancelAnimationFrame(settleRafRef.current);
      settleRafRef.current = null;
    }
  }, []);

  const settleAtEnd = useCallback(() => {
    cancelSettle();
    followRef.current = FOLLOWING_END;
    let attempts = 0;
    const step = () => {
      virtualizer.scrollToEnd();
      if (
        virtualizer.isAtEnd(THREAD_AT_END_THRESHOLD) ||
        ++attempts > SETTLE_AT_END_ATTEMPTS
      ) {
        settleRafRef.current = null;
        return;
      }
      settleRafRef.current = requestAnimationFrame(step);
    };
    step();
  }, [virtualizer, cancelSettle]);

  const settleToIndex = useCallback(
    (index: number) => {
      cancelSettle();
      // A jump is the reader choosing a spot in the thread; streamed content must not pull them off
      // it, even when the target happens to sit inside the at-end tolerance.
      followRef.current = { following: false, leftEnd: true };
      virtualizer.scrollToIndex(index, { align: "start" });
      let attempts = 0;
      const step = () => {
        settleRafRef.current = null;
        const viewport = viewportRef.current;
        const target = virtualizer.getOffsetForIndex(index, "start")?.[0];
        if (!viewport || target == null) return;
        const maxScroll = Math.max(
          0,
          viewport.scrollHeight - viewport.clientHeight,
        );
        if (
          Math.abs(viewport.scrollTop - Math.min(target, maxScroll)) <= 1 ||
          ++attempts > SETTLE_TO_INDEX_ATTEMPTS
        ) {
          return;
        }
        virtualizer.scrollToIndex(index, { align: "start" });
        settleRafRef.current = requestAnimationFrame(step);
      };
      settleRafRef.current = requestAnimationFrame(step);
    },
    [virtualizer, viewportRef, cancelSettle],
  );

  /**
   * An upward gesture: leave following until the reader scrolls back down into the end tolerance.
   * Ignored when there is nothing above to reach — a stray wheel over a thread that fits the
   * viewport would otherwise kill following with no scroll event left to undo it.
   */
  const leaveEnd = useCallback(() => {
    if (followRef.current.leftEnd) return;
    if ((viewportRef.current?.scrollTop ?? 0) <= 0) return;
    followRef.current = { following: false, leftEnd: true };
  }, [viewportRef]);

  useEffect(() => cancelSettle, [cancelSettle]);

  return { followRef, leaveEnd, settleAtEnd, settleToIndex };
}

/**
 * Current-turn anchor derived from the virtualizer's measurements (estimated for rows that have
 * never mounted, exact once measured), recomputed at most once per frame. Returns the state plus
 * the scheduler the scroll handler pokes. The engine's own visibility state only sees mounted
 * rows, so the minimap reads this instead.
 */
function useStickyAnchor(
  virtualizer: ThreadVirtualizer,
  viewportRef: RefObject<HTMLDivElement | null>,
  userRows: readonly UserRow[],
  totalSize: number,
) {
  const [state, setState] = useState<StickyAnchorState>({ anchorId: null });

  const recompute = useCallback(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const cache = virtualizer.measurementsCache;
    const entries: StickyAnchorEntry[] = userRows.map((user) => {
      const measured = cache[user.index];
      const start = measured?.start ?? user.index * ESTIMATED_ROW_SIZE;
      const end = measured?.end ?? start + ESTIMATED_ROW_SIZE;
      return { id: user.id, start, end };
    });
    const next = computeStickyAnchor(
      entries,
      viewport.scrollTop,
      SCROLL_PREVIOUS_ITEM_PEEK,
    );
    setState((prev) => (prev.anchorId === next.anchorId ? prev : next));
  }, [userRows, virtualizer, viewportRef]);

  const frameRef = useRef<number | null>(null);
  const schedule = useCallback(() => {
    if (frameRef.current != null) return;
    frameRef.current = requestAnimationFrame(() => {
      frameRef.current = null;
      recompute();
    });
  }, [recompute]);

  // Re-derive on mount, whenever the row set changes, and whenever the measurement cache moves —
  // `totalSize` is its cheapest proxy. Async markdown/diff/tool content can grow a mounted row
  // with no scroll and no row-set change, shifting every anchor below it; without this trigger
  // the pill holds the stale anchor until the next scroll.
  // biome-ignore lint/correctness/useExhaustiveDependencies: totalSize is the remeasure trigger, not a body dependency
  useEffect(() => {
    schedule();
    return () => {
      if (frameRef.current != null) {
        cancelAnimationFrame(frameRef.current);
        frameRef.current = null;
      }
    };
  }, [schedule, totalSize]);

  return { state, schedule };
}

/**
 * Keeps the view pinned to the bottom while following. Three triggers, all of which the
 * virtualizer's own `anchorTo`/`followOnAppend` miss:
 * - `totalSize` moving (rows remeasuring past the estimate, late async content growing rows, the
 *   footer resize feeding `paddingEnd`) — a layout effect so the re-pin lands before paint;
 * - a prompt submitted from anywhere, which re-engages follow (the trigger `ThreadAutoFollow` uses
 *   in the non-virtualized body);
 * - returning to a backgrounded tab, where ResizeObserver callbacks were throttled.
 */
function useFollowBottom({
  virtualizer,
  totalSize,
  items,
  followRef,
  settleAtEnd,
}: {
  virtualizer: ThreadVirtualizer;
  totalSize: number;
  items: ConversationItem[];
  followRef: RefObject<ThreadFollowState>;
  settleAtEnd: () => void;
}) {
  // biome-ignore lint/correctness/useExhaustiveDependencies: totalSize is the trigger, not a body dependency
  useLayoutEffect(() => {
    if (!followRef.current.following) return;
    virtualizer.scrollToEnd();
  }, [totalSize, virtualizer, followRef]);

  const lastItem = items.at(-1);
  const userMessageCount = useMemo(
    () =>
      items.reduce((n, item) => (item.type === "user_message" ? n + 1 : n), 0),
    [items],
  );
  const prevUserCountRef = useRef(userMessageCount);
  useLayoutEffect(() => {
    const previous = prevUserCountRef.current;
    prevUserCountRef.current = userMessageCount;
    if (previous === 0 || userMessageCount <= previous) return;
    if (lastItem?.type !== "user_message") return;
    settleAtEnd();
  }, [userMessageCount, lastItem, settleAtEnd]);

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (!document.hidden && followRef.current.following) settleAtEnd();
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () =>
      document.removeEventListener("visibilitychange", handleVisibilityChange);
  }, [settleAtEnd, followRef]);
}

/**
 * Windowed scroll body for long threads, following the upstream MessageScroller guidance:
 * virtualization lives outside the primitive — the quill viewport stays the scroll element and a
 * `@tanstack/react-virtual` virtualizer owns the rows inside `ChatMessageScrollerContent`.
 *
 * The engine still provides the chrome that only needs scroll geometry (the scroll-to-bottom
 * button and edge state read real element measurements), while everything item-based gets a
 * windowed implementation here: follow-bottom via `anchorTo: "end"` + `followOnAppend` (the legacy
 * `VirtualizedList` recipe), message jumps via `scrollToIndex`, the sticky header via
 * `computeStickyAnchor` over the virtualizer's measurements.
 */
export function VirtualThreadScrollBody({
  items,
  flatRows,
  renderRow,
  footer,
  onUserInteract,
  renderNav,
  resumeRef,
  olderHistoryCursor = 0,
  isLoadingOlderHistory = false,
  onLoadOlderHistory,
}: {
  items: ConversationItem[];
  flatRows: FlatThreadRow[];
  renderRow: (row: FlatThreadRow) => ReactNode;
  /** Status row (duration / context usage) pinned as the last item in the thread. */
  footer?: ReactNode;
  /** Clears keyboard-focused message state on any pointer interaction with the thread. */
  onUserInteract?: () => void;
  /**
   * Navigation layer, rendered as a sibling of the scroller so it can be handed this body's jump
   * implementation, because the engine's `scrollToMessage` only reaches mounted rows. The jump
   * reports whether the target resolved, so a caller can retry rather than fail silently.
   */
  renderNav?: (jumpToMessage: (id: string) => boolean) => ReactNode;
  /** Where the non-virtualized body left off, read once when this body takes over mid-session. */
  resumeRef: RefObject<ThreadScrollResume>;
  /**
   * Chain index of the oldest loaded entry; 0 means the whole transcript is loaded. Doubles as the
   * loader's progress signal, because it only moves when a page actually lands.
   */
  olderHistoryCursor?: number;
  isLoadingOlderHistory?: boolean;
  onLoadOlderHistory?: () => void;
}) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const footerRef = useRef<HTMLDivElement | null>(null);
  const initializedRef = useRef(false);
  const lastScrollTopRef = useRef(0);

  const hasFooter = footer != null;
  const footerHeight = useReservedFooterHeight(footerRef, hasFooter);

  const virtualizer = useVirtualizer({
    count: flatRows.length,
    getScrollElement: () => viewportRef.current,
    estimateSize: () => ESTIMATED_ROW_SIZE,
    overscan: OVERSCAN,
    anchorTo: "end",
    followOnAppend: true,
    scrollEndThreshold: THREAD_AT_END_THRESHOLD,
    paddingStart: PADDING_START,
    paddingEnd: footerHeight,
    getItemKey: (index) => flatRows[index]?.key ?? index,
  });

  const loadOlderArmedRef = useRef(false);
  const canLoadOlderRef = useRef(false);
  const isLoadingOlderRef = useRef(isLoadingOlderHistory);
  isLoadingOlderRef.current = isLoadingOlderHistory;
  const onLoadOlderHistoryRef = useRef(onLoadOlderHistory);
  useEffect(() => {
    onLoadOlderHistoryRef.current = onLoadOlderHistory;
  }, [onLoadOlderHistory]);

  const maybeLoadOlderHistory = useCallback(() => {
    const el = viewportRef.current;
    if (!el) return;
    const next = nextOlderHistoryLoadState(loadOlderArmedRef.current, {
      canLoad: canLoadOlderRef.current,
      isLoading: isLoadingOlderRef.current,
      scrollTop: el.scrollTop,
      maxScrollTop: el.scrollHeight - el.clientHeight,
    });
    loadOlderArmedRef.current = next.armed;
    if (next.load) onLoadOlderHistoryRef.current?.();
  }, []);

  // Arming belongs to the scroll handler, so one gesture buys one page. This
  // only covers what a gesture cannot reach: the first cursor the body sees, and
  // a viewport parked with no scroll room, which emits no scroll events at all.
  // Arming on every cursor move would instead chain page after page, because a
  // page of collapsed tool rows lands the viewport back inside the threshold.
  useEffect(() => {
    const canLoad = olderHistoryCursor > 0 && onLoadOlderHistory != null;
    const becameAvailable = canLoad && !canLoadOlderRef.current;
    canLoadOlderRef.current = canLoad;
    if (!canLoad) {
      loadOlderArmedRef.current = false;
      return;
    }
    if (becameAvailable) loadOlderArmedRef.current = true;
    const id = window.setTimeout(maybeLoadOlderHistory, 250);
    return () => window.clearTimeout(id);
  }, [olderHistoryCursor, onLoadOlderHistory, maybeLoadOlderHistory]);

  const { followRef, leaveEnd, settleAtEnd, settleToIndex } = useSettleControls(
    virtualizer,
    viewportRef,
  );

  const userRows = useMemo(() => {
    const result: UserRow[] = [];
    flatRows.forEach((row, index) => {
      if (row.item.type === "user_message") {
        result.push({ id: row.item.id, index });
      }
    });
    return result;
  }, [flatRows]);

  // Held in a ref so `jumpToMessage` stays referentially stable across appends — it is handed to
  // the nav layer and to the sticky header, neither of which should re-render per streamed chunk.
  const rowIndexByMessageId = useMemo(() => {
    const map = new Map<string, number>();
    flatRows.forEach((row, index) => {
      map.set(row.item.id, index);
    });
    return map;
  }, [flatRows]);
  const rowIndexRef = useRef(rowIndexByMessageId);
  rowIndexRef.current = rowIndexByMessageId;

  const jumpToMessage = useCallback(
    (id: string) => {
      const index = rowIndexRef.current.get(id);
      if (index == null) return false;
      settleToIndex(index);
      return true;
    },
    [settleToIndex],
  );

  // Initial position: resume at the message the non-virtualized body was anchored to, or settle at
  // the bottom. Resuming by row index rather than by pixel offset is what makes the handoff land —
  // the two bodies don't share a coordinate space (virtual offsets are estimates until rows
  // measure), so a recorded `scrollTop` would mean nothing here.
  useLayoutEffect(() => {
    if (initializedRef.current || flatRows.length === 0) return;
    initializedRef.current = true;
    const { atBottom, anchorId } = resumeRef.current;
    const anchorIndex =
      anchorId != null ? rowIndexRef.current.get(anchorId) : undefined;
    if (!atBottom && anchorIndex != null) {
      settleToIndex(anchorIndex);
      return;
    }
    settleAtEnd();
  }, [flatRows.length, settleAtEnd, settleToIndex, resumeRef]);

  const totalSize = virtualizer.getTotalSize();

  const { state: stickyState, schedule: scheduleStickyRecompute } =
    useStickyAnchor(virtualizer, viewportRef, userRows, totalSize);

  const handleScroll = useCallback(() => {
    const el = viewportRef.current;
    if (el) {
      const sample = sampleThreadScroll(el, lastScrollTopRef.current);
      lastScrollTopRef.current = el.scrollTop;
      followRef.current = nextThreadFollowState(followRef.current, sample);
      maybeLoadOlderHistory();
    }
    scheduleStickyRecompute();
  }, [scheduleStickyRecompute, followRef, maybeLoadOlderHistory]);

  useFollowBottom({
    virtualizer,
    totalSize,
    items,
    followRef,
    settleAtEnd,
  });

  const virtualItems = virtualizer.getVirtualItems();

  return (
    <>
      <ChatMessageScroller
        className="@container/thread group/thread"
        onPointerDownCapture={onUserInteract}
      >
        <MessageMinimap
          items={items}
          onJump={jumpToMessage}
          anchorId={stickyState.anchorId}
        />
        {isLoadingOlderHistory && (
          <div className="-translate-x-1/2 pointer-events-none absolute top-2 left-1/2 z-10 rounded-full border border-(--gray-5) bg-(--gray-2) px-3 py-1 text-(--gray-11) text-xs">
            Loading earlier messages…
          </div>
        )}
        <ChatMessageScrollerViewport
          ref={viewportRef}
          onScroll={handleScroll}
          // Reading upward is intent, not geometry: these catch a gesture too small to register as
          // a direction change in the scroll handler, which would otherwise still measure "at the
          // end" and let the next streamed chunk undo it.
          onWheelCapture={(event: ReactWheelEvent) => {
            if (event.deltaY < 0) leaveEnd();
          }}
          onTouchMoveCapture={leaveEnd}
          onKeyDownCapture={(event: ReactKeyboardEvent) => {
            if (SCROLL_UP_KEYS.has(event.key)) leaveEnd();
          }}
        >
          {/* `block` overrides the content's flex+gap layout — spacing moves into the rows
              (pb-4) and the virtual paddings, so translateY offsets are the whole layout. */}
          <ChatMessageScrollerContent
            className="block"
            density="default"
            style={{ paddingInline: CHAT_CONTENT_PADDING_INLINE }}
          >
            <div className="relative w-full" style={{ height: totalSize }}>
              {virtualItems.map((virtualItem) => {
                const row = flatRows[virtualItem.index];
                if (!row) return null;
                return (
                  <div
                    key={virtualItem.key}
                    ref={virtualizer.measureElement}
                    data-index={virtualItem.index}
                    className="absolute top-0 left-0 w-full"
                    style={{ transform: `translateY(${virtualItem.start}px)` }}
                  >
                    {renderRow(row)}
                  </div>
                );
              })}
              {/* Footer occupies the reserved paddingEnd region at the very bottom of the virtual
                  space, so the DOM bottom == the virtual end. */}
              {hasFooter && (
                <div
                  ref={footerRef}
                  className="absolute bottom-0 left-0 w-full"
                >
                  <div
                    className="mx-auto w-full px-2.5 pb-8"
                    style={{ maxWidth: CHAT_CONTENT_MAX_WIDTH }}
                  >
                    {footer}
                  </div>
                </div>
              )}
            </div>
          </ChatMessageScrollerContent>
        </ChatMessageScrollerViewport>
        <ChatMessageScrollerButton
          onClick={(event: ReactMouseEvent) => {
            // The engine's own scroll-to-end targets the current scrollHeight, which is an
            // estimate until every row between here and the bottom has measured — settle instead.
            // (The primitive skips its own handler once the event is defaultPrevented.)
            event.preventDefault();
            settleAtEnd();
          }}
        />
      </ChatMessageScroller>
      {renderNav?.(jumpToMessage)}
    </>
  );
}
