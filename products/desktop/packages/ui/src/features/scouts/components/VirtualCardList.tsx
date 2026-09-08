import { useVirtualizer } from "@tanstack/react-virtual";
import { type ReactNode, useLayoutEffect, useRef } from "react";

const OVERSCAN = 6;

/**
 * A scrolling column of cards that renders only what is in view. The signal and
 * memory lists hold hundreds of cards, each one a rendered markdown note, so
 * drawing them all freezes the screen for about a second when the page opens.
 */
export function VirtualCardList<T>({
  items,
  getKey,
  renderItem,
  estimateSize,
  gap = 8,
  resetKey,
}: {
  items: T[];
  getKey: (item: T, index: number) => string;
  renderItem: (item: T, index: number) => ReactNode;
  /** First guess at a card's height; each card measures itself once it renders. */
  estimateSize: number;
  gap?: number;
  resetKey?: string;
}) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => viewportRef.current,
    estimateSize: () => estimateSize,
    getItemKey: (index) => {
      const item = items[index];
      return item === undefined ? index : getKey(item, index);
    },
    overscan: OVERSCAN,
    gap,
  });

  useLayoutEffect(() => {
    if (resetKey !== undefined) virtualizer.scrollToOffset(0);
  }, [resetKey, virtualizer]);

  return (
    <div ref={viewportRef} className="min-h-0 flex-1 overflow-y-auto">
      <div
        className="relative w-full"
        style={{ height: virtualizer.getTotalSize() }}
      >
        {virtualizer.getVirtualItems().map((virtualItem) => {
          const item = items[virtualItem.index];
          if (item === undefined) return null;
          return (
            <div
              key={virtualItem.key}
              ref={virtualizer.measureElement}
              data-index={virtualItem.index}
              className="absolute top-0 left-0 w-full"
              style={{ transform: `translateY(${virtualItem.start}px)` }}
            >
              {renderItem(item, virtualItem.index)}
            </div>
          );
        })}
      </div>
    </div>
  );
}
