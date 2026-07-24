import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import type { ConversationSearchBarHandle } from "@posthog/ui/features/sessions/components/ConversationSearchBar";
import type { VirtualizedListHandle } from "@posthog/ui/features/sessions/components/VirtualizedList";
import { extractSearchableText } from "@posthog/ui/features/sessions/utils/extractSearchableText";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const HIGHLIGHT_MATCH = "search-match";
const HIGHLIGHT_ACTIVE = "search-match-active";

interface SearchMatch {
  itemIndex: number;
  itemId: string;
  occurrenceInItem: number;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function clearHighlights() {
  if (typeof CSS === "undefined" || !CSS.highlights) return;
  CSS.highlights.delete(HIGHLIGHT_MATCH);
  CSS.highlights.delete(HIGHLIGHT_ACTIVE);
}

function findItemElement(
  container: HTMLElement,
  itemId: string,
): HTMLElement | null {
  return container.querySelector(
    `[data-conversation-item-id="${CSS.escape(itemId)}"]`,
  );
}

function findRangesInItem(itemEl: HTMLElement, query: string): Range[] {
  const ranges: Range[] = [];
  const re = new RegExp(escapeRegExp(query), "gi");
  const walker = document.createTreeWalker(itemEl, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const text = node.textContent ?? "";
    if (!text) continue;
    re.lastIndex = 0;
    let m: RegExpExecArray | null = re.exec(text);
    while (m !== null) {
      const range = new Range();
      range.setStart(node, m.index);
      range.setEnd(node, m.index + m[0].length);
      ranges.push(range);
      if (m.index === re.lastIndex) re.lastIndex++;
      m = re.exec(text);
    }
  }
  return ranges;
}

interface UseConversationSearchArgs {
  items: ConversationItem[];
  containerRef: React.RefObject<HTMLDivElement | null>;
  listRef: React.RefObject<VirtualizedListHandle | null>;
}

export function useConversationSearch({
  items,
  containerRef,
  listRef,
}: UseConversationSearchArgs) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [currentIndex, setCurrentIndex] = useState(0);
  const searchBarRef = useRef<ConversationSearchBarHandle>(null);

  const matches = useMemo<SearchMatch[]>(() => {
    if (!query) return [];
    const re = new RegExp(escapeRegExp(query), "gi");
    const out: SearchMatch[] = [];
    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      const text = extractSearchableText(item);
      if (!text) continue;
      re.lastIndex = 0;
      let occurrence = 0;
      let m: RegExpExecArray | null = re.exec(text);
      while (m !== null) {
        out.push({
          itemIndex: i,
          itemId: item.id,
          occurrenceInItem: occurrence++,
        });
        if (m.index === re.lastIndex) re.lastIndex++;
        m = re.exec(text);
      }
    }
    return out;
  }, [items, query]);

  const setQueryAndReset = useCallback((q: string) => {
    setQuery(q);
    setCurrentIndex(0);
  }, []);

  const next = useCallback(() => {
    if (matches.length === 0) return;
    const i = (currentIndex + 1) % matches.length;
    setCurrentIndex(i);
    listRef.current?.scrollToIndex(matches[i].itemIndex);
  }, [matches, currentIndex, listRef]);

  const prev = useCallback(() => {
    if (matches.length === 0) return;
    const i = (currentIndex - 1 + matches.length) % matches.length;
    setCurrentIndex(i);
    listRef.current?.scrollToIndex(matches[i].itemIndex);
  }, [matches, currentIndex, listRef]);

  const close = useCallback(() => {
    setOpen(false);
    setQuery("");
    setCurrentIndex(0);
    clearHighlights();
  }, []);

  useEffect(() => {
    if (!query || matches.length === 0) return;
    listRef.current?.scrollToIndex(matches[0].itemIndex);
  }, [query, matches, listRef]);

  // Apply CSS Custom Highlights. Reapplies whenever the virtualized list
  // mutates the DOM (items entering/leaving the viewport), so no scroll
  // listener or timeout retries are needed.
  useEffect(() => {
    if (typeof CSS === "undefined" || !CSS.highlights) return;
    const container = containerRef.current;
    if (!container || !query || matches.length === 0) {
      clearHighlights();
      return;
    }

    const matchesByItemId = new Map<string, SearchMatch[]>();
    for (const m of matches) {
      const list = matchesByItemId.get(m.itemId);
      if (list) list.push(m);
      else matchesByItemId.set(m.itemId, [m]);
    }

    const active = matches[currentIndex] ?? null;

    function apply() {
      clearHighlights();
      const allRanges: Range[] = [];
      let activeRange: Range | null = null;

      for (const [itemId] of matchesByItemId) {
        const itemEl = findItemElement(container as HTMLElement, itemId);
        if (!itemEl) continue;
        const domRanges = findRangesInItem(itemEl, query);
        for (const r of domRanges) allRanges.push(r);
        if (active && active.itemId === itemId && domRanges.length > 0) {
          // Pick the DOM occurrence matching the data-model occurrence
          // within this item. If the DOM has fewer occurrences (e.g.
          // markdown collapsed whitespace), fall back to the last one.
          const idx = Math.min(active.occurrenceInItem, domRanges.length - 1);
          activeRange = domRanges[idx];
        }
      }

      if (allRanges.length > 0) {
        CSS.highlights.set(HIGHLIGHT_MATCH, new Highlight(...allRanges));
      }
      if (activeRange) {
        CSS.highlights.set(HIGHLIGHT_ACTIVE, new Highlight(activeRange));
      }
    }

    apply();

    const observer = new MutationObserver(apply);
    observer.observe(container, {
      childList: true,
      subtree: true,
      characterData: true,
    });

    return () => {
      observer.disconnect();
    };
  }, [containerRef, query, matches, currentIndex]);

  // Global Cmd+F: open the search bar, or refocus + select-all if open.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.key !== "f") return;
      e.preventDefault();
      setOpen(true);
      searchBarRef.current?.focusAndSelect();
    };
    document.addEventListener("keydown", onKeyDown, { capture: true });
    return () =>
      document.removeEventListener("keydown", onKeyDown, { capture: true });
  }, []);

  return {
    open,
    query,
    currentIndex,
    totalMatches: matches.length,
    searchBarRef,
    setQuery: setQueryAndReset,
    next,
    prev,
    close,
  };
}
