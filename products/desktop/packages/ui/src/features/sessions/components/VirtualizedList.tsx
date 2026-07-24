import { cn } from "@posthog/quill";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  type CSSProperties,
  forwardRef,
  type ReactNode,
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

interface VirtualizedListProps<T> {
  items: T[];
  renderItem: (item: T, index: number) => ReactNode;
  getItemKey?: (item: T, index: number) => string | number;
  className?: string;
  itemClassName?: string;
  itemStyle?: CSSProperties;
  footer?: ReactNode;
  onScrollStateChange?: (isAtBottom: boolean) => void;
  keepMounted?: readonly number[];
  /**
   * Allow horizontal scrolling of the list viewport. Defaults to true. Narrow
   * surfaces (e.g. the Agent Builder dock) pass false so off-edge content like
   * a message's hover action can't produce a horizontal scrollbar; nested
   * scrollers (code blocks) keep their own overflow.
   */
  scrollX?: boolean;
}

export interface VirtualizedListHandle {
  scrollToBottom: () => void;
  scrollToIndex: (index: number) => void;
}

const AT_BOTTOM_THRESHOLD = 50;
const ESTIMATED_ROW_SIZE = 80;
// Render rows well ahead so tall, async rows (markdown, code, diffs) measure and
// paint off-screen instead of shifting and stuttering as they enter view. 12
// erases the scroll-up shift empirically; higher only adds DOM cost.
const OVERSCAN = 12;
// A real upward drift, not a 1-frame measure transient: the DOM bottom sits
// this far below the viewport. Well above any single append's measure gap.
const FAR_DRIFT_THRESHOLD = 400;

function VirtualizedListInner<T>(
  {
    items,
    renderItem,
    getItemKey,
    className,
    itemClassName,
    itemStyle,
    footer,
    onScrollStateChange,
    keepMounted,
    scrollX = true,
  }: VirtualizedListProps<T>,
  ref: React.ForwardedRef<VirtualizedListHandle>,
) {
  const parentRef = useRef<HTMLDivElement>(null);
  const footerRef = useRef<HTMLDivElement>(null);
  const initializedRef = useRef(false);
  const isAtBottomRef = useRef(true);
  const lastScrollTopRef = useRef(0);
  const settlingRef = useRef(false);
  const settleRafRef = useRef<number | null>(null);
  const onScrollStateChangeRef = useRef(onScrollStateChange);
  onScrollStateChangeRef.current = onScrollStateChange;

  const hasFooter = footer != null;

  // The footer is real trailing content, NOT a fake virtual row. As a virtual
  // row it would have a constant key and always be last, which permanently
  // kills tanstack's followOnAppend (it only fires when the last virtual key
  // changes on append). Instead we reserve its height as `paddingEnd` so the
  // virtual coordinate space includes it: anchorTo='end' then pins to BELOW the
  // footer, and isAtEnd lines up with the real DOM bottom. With the footer out
  // of the count, the last virtual item is the real last message, so
  // followOnAppend handles appends and anchorTo handles in-place growth (tokens)
  // natively — no hand-rolled scroll-following.
  const [footerHeight, setFooterHeight] = useState(0);

  useLayoutEffect(() => {
    const el = footerRef.current;
    if (!hasFooter || !el) {
      setFooterHeight(0);
      return;
    }
    setFooterHeight(el.offsetHeight);
    const ro = new ResizeObserver(() => {
      const h = el.offsetHeight;
      setFooterHeight((prev) => (prev === h ? prev : h));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [hasFooter]);

  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ESTIMATED_ROW_SIZE,
    overscan: OVERSCAN,
    anchorTo: "end",
    followOnAppend: true,
    scrollEndThreshold: AT_BOTTOM_THRESHOLD,
    paddingEnd: footerHeight,
    getItemKey: (index) => {
      const item = items[index];
      return getItemKey ? getItemKey(item, index) : index;
    },
  });

  const settleAtEnd = useCallback(() => {
    if (settleRafRef.current !== null) {
      cancelAnimationFrame(settleRafRef.current);
      settleRafRef.current = null;
    }
    settlingRef.current = true;
    isAtBottomRef.current = true;
    let attempts = 0;
    const step = () => {
      virtualizer.scrollToEnd();
      if (virtualizer.isAtEnd(AT_BOTTOM_THRESHOLD)) {
        settlingRef.current = false;
        settleRafRef.current = null;
        if (initializedRef.current) {
          onScrollStateChangeRef.current?.(true);
        }
        return;
      }
      if (++attempts > 12) {
        settlingRef.current = false;
        settleRafRef.current = null;
        return;
      }
      settleRafRef.current = requestAnimationFrame(step);
    };
    step();
  }, [virtualizer]);

  useImperativeHandle(
    ref,
    () => ({
      scrollToBottom: settleAtEnd,
      scrollToIndex: (index: number) => {
        if (settleRafRef.current !== null) {
          cancelAnimationFrame(settleRafRef.current);
          settleRafRef.current = null;
          settlingRef.current = false;
        }
        isAtBottomRef.current = false;
        virtualizer.scrollToIndex(index, { align: "center" });
      },
    }),
    [virtualizer, settleAtEnd],
  );

  useEffect(() => {
    return () => {
      if (settleRafRef.current !== null) {
        cancelAnimationFrame(settleRafRef.current);
      }
    };
  }, []);

  useLayoutEffect(() => {
    if (initializedRef.current || items.length === 0) return;
    // settleAtEnd retries across frames so the initial scroll survives rows
    // measuring taller than the 80px estimate.
    settleAtEnd();
    requestAnimationFrame(() => {
      initializedRef.current = true;
    });
  }, [items.length, settleAtEnd]);

  const totalSize = virtualizer.getTotalSize();

  // Anything that changes the virtual height while we're following has to re-pin
  // to the new bottom: rows remeasuring past the 80px estimate, late async
  // content (syntax highlighting, diffs) growing rows, and the footer's own
  // resize (which feeds paddingEnd). tanstack's anchor logic only watches item
  // count/keys, so none of these trigger it — totalSize is the one value that
  // moves for all of them, so key the re-pin off it.
  //
  // Gate on isAtBottomRef (true until the user scrolls up), NOT initializedRef.
  // footerHeight starts at 0, so the initial settle pins to a bottom that
  // excludes the footer; the footer then measures and grows paddingEnd before
  // initializedRef flips, stranding us above the real bottom. Running pre-init
  // closes that gap. This is a layout effect so the re-pin lands synchronously,
  // before paint — no visible drift, no transient isAtEnd=false flicker.
  // biome-ignore lint/correctness/useExhaustiveDependencies: totalSize is the trigger, not a body dependency
  useLayoutEffect(() => {
    if (!isAtBottomRef.current) return;
    virtualizer.scrollToEnd();
  }, [totalSize, virtualizer]);

  const handleScroll = useCallback(() => {
    const el = parentRef.current;
    const scrollTop = el?.scrollTop ?? 0;
    // Tolerate sub-pixel jitter; only a real upward move counts as leaving end.
    const scrolledUp = scrollTop < lastScrollTopRef.current - 1;
    lastScrollTopRef.current = scrollTop;

    const atEnd = virtualizer.isAtEnd(AT_BOTTOM_THRESHOLD);
    // Genuine far drift (not a 1-frame measure transient): the DOM bottom sits
    // well below the viewport.
    const farFromEnd = el
      ? el.scrollHeight - el.clientHeight - scrollTop > FAR_DRIFT_THRESHOLD
      : false;
    // Hysteresis for the scroll-to-bottom button (pure UI state — tanstack still
    // drives the actual scrolling). Each append measures taller than the 80px
    // estimate, so for one frame isAtEnd reads false before followOnAppend /
    // anchorTo re-pin. Reporting that transient flickers the button. Re-arm
    // "at bottom" whenever we reach the end; only clear it when the user
    // actually scrolls up. Growth pins down (scrollTop holds or rises), so it
    // never trips the scrolledUp branch.
    // Surface the button on a real upward scroll, or on a genuine far drift so
    // follow can't get silently stuck mid-thread.
    if (atEnd) {
      isAtBottomRef.current = true;
    } else if (scrolledUp || farFromEnd) {
      isAtBottomRef.current = false;
    }

    if (!initializedRef.current) return;
    // Suppress intermediate "not at bottom" pings while a programmatic
    // scrollToEnd is still settling after row remeasure.
    if (settlingRef.current && !isAtBottomRef.current) return;
    onScrollStateChangeRef.current?.(isAtBottomRef.current);
  }, [virtualizer]);

  const virtualItems = virtualizer.getVirtualItems();

  const renderedIndices = useMemo(() => {
    const set = new Set<number>();
    for (const v of virtualItems) set.add(v.index);
    return set;
  }, [virtualItems]);

  const orphanKeepIndices = useMemo(() => {
    if (!keepMounted || keepMounted.length === 0) return [];
    return keepMounted.filter(
      (i) => i >= 0 && i < items.length && !renderedIndices.has(i),
    );
  }, [keepMounted, renderedIndices, items.length]);

  return (
    <div className={`flex h-full flex-col ${className ?? ""}`}>
      <div
        ref={parentRef}
        onScroll={handleScroll}
        className={`scroll-mask-8 flex-1 overflow-y-auto ${scrollX ? "overflow-x-auto" : "overflow-x-hidden"}`}
        style={{ scrollbarGutter: "stable" }}
      >
        <div
          style={{
            height: totalSize,
            position: "relative",
            width: "100%",
          }}
        >
          {virtualItems.map((virtualItem) => {
            const item = items[virtualItem.index];
            const itemKey = getItemKey
              ? getItemKey(item, virtualItem.index)
              : virtualItem.index;
            return (
              <div
                key={virtualItem.key}
                ref={virtualizer.measureElement}
                data-index={virtualItem.index}
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  width: "100%",
                  transform: `translateY(${virtualItem.start}px)`,
                }}
              >
                <div
                  className={cn(itemClassName, "[&_p:last-of-type]:mb-0")}
                  style={itemStyle}
                  data-conversation-item-id={itemKey}
                >
                  {renderItem(item, virtualItem.index)}
                </div>
              </div>
            );
          })}
          {orphanKeepIndices.map((index) => {
            const item = items[index];
            const k = getItemKey ? getItemKey(item, index) : index;
            return (
              <div
                key={`keep-${k}`}
                aria-hidden
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  width: "100%",
                  transform: "translateY(-99999px)",
                  pointerEvents: "none",
                  visibility: "hidden",
                }}
              >
                <div
                  className={itemClassName}
                  style={itemStyle}
                  data-conversation-item-id={k}
                >
                  {renderItem(item, index)}
                </div>
              </div>
            );
          })}
          {/* Footer occupies the reserved paddingEnd region at the very bottom
              of the virtual space, so the DOM bottom == the virtual end. */}
          {hasFooter && (
            <div
              ref={footerRef}
              style={{
                position: "absolute",
                bottom: 0,
                left: 0,
                width: "100%",
              }}
            >
              <div className={itemClassName} style={itemStyle}>
                {footer}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export const VirtualizedList = forwardRef(VirtualizedListInner) as <T>(
  props: VirtualizedListProps<T> & {
    ref?: React.ForwardedRef<VirtualizedListHandle>;
  },
) => ReturnType<typeof VirtualizedListInner>;
