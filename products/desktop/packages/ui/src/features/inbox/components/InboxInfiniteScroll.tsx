import { CardSkeleton } from "@posthog/ui/features/inbox/components/CardSkeleton";
import { useEffect, useRef } from "react";

// Generous prefetch margin so the next page lands well before the user
// reaches the bottom.
const PREFETCH_MARGIN = "1500px";

// The margin only works when the observer's root is the element that actually
// clips the list (the inbox scrolls inside an inner overflow container, not
// the viewport): with the default viewport root, a clipped sentinel never
// intersects until it is literally on screen.
function nearestScrollContainer(el: HTMLElement): Element | null {
  let node = el.parentElement;
  while (node) {
    const { overflowY } = getComputedStyle(node);
    if (overflowY === "auto" || overflowY === "scroll") return node;
    node = node.parentElement;
  }
  return null;
}

interface InboxInfiniteScrollProps {
  hasNextPage: boolean | undefined;
  isFetchingNextPage: boolean;
  onLoadMore: () => void;
}

/**
 * Advances a paginated inbox list as the user approaches the bottom, with
 * skeleton cards continuing the list while the next page loads. Replaces the
 * old explicit "Load more" button.
 */
export function InboxInfiniteScroll({
  hasNextPage,
  isFetchingNextPage,
  onLoadMore,
}: InboxInfiniteScrollProps) {
  const sentinelRef = useRef<HTMLDivElement>(null);

  // Read fresh state at intersection time via refs so the observer is created
  // once per mount instead of twice per page fetch (`hasNextPage` and
  // `isFetchingNextPage` both flip during a load), and inline callback
  // identities don't churn it either.
  const hasNextRef = useRef(hasNextPage);
  hasNextRef.current = hasNextPage;
  const fetchingRef = useRef(isFetchingNextPage);
  fetchingRef.current = isFetchingNextPage;
  const loadMoreRef = useRef(onLoadMore);
  loadMoreRef.current = onLoadMore;

  const active = hasNextPage === true;
  useEffect(() => {
    const el = sentinelRef.current;
    if (!active || !el) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (
          entries[0]?.isIntersecting &&
          hasNextRef.current &&
          !fetchingRef.current
        ) {
          loadMoreRef.current();
        }
      },
      { root: nearestScrollContainer(el), rootMargin: PREFETCH_MARGIN },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [active]);

  if (!active) return null;

  return (
    <>
      {isFetchingNextPage && <CardSkeleton count={2} variant="cards" />}
      <div ref={sentinelRef} className="h-px" aria-hidden />
    </>
  );
}
