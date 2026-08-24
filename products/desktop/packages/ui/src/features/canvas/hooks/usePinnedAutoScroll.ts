import { useCallback, useLayoutEffect, useRef } from "react";

const BOTTOM_TOLERANCE_PX = 1;

export function isScrolledToBottom(element: HTMLElement): boolean {
  return (
    element.scrollHeight - element.scrollTop - element.clientHeight <=
    BOTTOM_TOLERANCE_PX
  );
}

/** Keeps growing content in view until the viewer deliberately scrolls away. */
export function usePinnedAutoScroll() {
  const containerRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const isPinnedRef = useRef(true);

  const scrollToBottom = useCallback(() => {
    const container = containerRef.current;
    if (container && isPinnedRef.current) {
      container.scrollTop = container.scrollHeight;
    }
  }, []);

  const onScroll = useCallback(() => {
    const container = containerRef.current;
    if (container) {
      isPinnedRef.current = isScrolledToBottom(container);
    }
  }, []);

  useLayoutEffect(() => {
    const content = contentRef.current;
    scrollToBottom();

    if (!content) {
      return;
    }

    const observer = new ResizeObserver(scrollToBottom);
    observer.observe(content);
    return () => observer.disconnect();
  }, [scrollToBottom]);

  return { containerRef, contentRef, onScroll };
}
