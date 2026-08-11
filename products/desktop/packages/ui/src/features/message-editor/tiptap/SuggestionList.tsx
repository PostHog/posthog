import { FolderIcon } from "@phosphor-icons/react";
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemMedia,
  ItemMenuItem,
  ItemTitle,
  Kbd,
} from "@posthog/quill";
import { FileIcon } from "@posthog/ui/primitives/FileIcon";
import {
  forwardRef,
  type ReactNode,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { SuggestionStatus } from "../components/SuggestionStatus";
import type { SuggestionItem } from "../types";

export interface SuggestionListRef {
  onKeyDown: (props: { event: KeyboardEvent }) => boolean;
}

export interface SuggestionListProps {
  items: SuggestionItem[];
  command: (item: SuggestionItem) => void;
  renderItem?: (item: SuggestionItem) => ReactNode;
  loading?: boolean;
}

// The same surface quill's own menu popups draw (see `.quill-autocomplete__content`),
// expressed in tokens rather than raw Radix vars so it tracks the design system.
// tippy owns the positioning, so there is no anchor width to inherit.
const CONTAINER_CLASS =
  "flex w-max min-w-[300px] max-w-[440px] flex-col overflow-hidden rounded-md border border-border bg-card text-[13px] text-foreground shadow-md";

function DefaultRow({ item }: { item: SuggestionItem }) {
  const isFolder = item.chipType === "folder";
  return (
    <Item size="xs" className="border-0 p-0">
      {item.filename && (
        <ItemMedia variant="icon" className="mt-0.5 self-start">
          {isFolder ? (
            <FolderIcon size={14} />
          ) : (
            <FileIcon filename={item.filename} size={14} />
          )}
        </ItemMedia>
      )}
      <ItemContent variant="menuItem" className="p-0">
        <ItemTitle className="truncate text-left">{item.label}</ItemTitle>
        {item.description && (
          <ItemDescription className="truncate text-left">
            {item.description}
          </ItemDescription>
        )}
      </ItemContent>
    </Item>
  );
}

export const SuggestionList = forwardRef<
  SuggestionListRef,
  SuggestionListProps
>(({ items, command, renderItem, loading = false }, ref) => {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const [hasMouseMoved, setHasMouseMoved] = useState(false);
  const prevItemsRef = useRef(items);

  if (prevItemsRef.current !== items) {
    prevItemsRef.current = items;
    setSelectedIndex(0);
    setHasMouseMoved(false);
  }

  // biome-ignore lint/correctness/useExhaustiveDependencies: re-scroll when items change
  useEffect(() => {
    itemRefs.current[selectedIndex]?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex, items]);

  useImperativeHandle(ref, () => ({
    onKeyDown: ({ event }) => {
      if (event.key === "ArrowUp") {
        setSelectedIndex((i) => (i + items.length - 1) % items.length);
        return true;
      }
      if (event.key === "ArrowDown") {
        setSelectedIndex((i) => (i + 1) % items.length);
        return true;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        if (items[selectedIndex]) {
          command(items[selectedIndex]);
          return true;
        }
        return false;
      }
      return false;
    },
  }));

  if (items.length === 0) {
    return (
      <div className={CONTAINER_CLASS}>
        <div className="p-2">
          <SuggestionStatus loading={loading} emptyMessage="No results found" />
        </div>
      </div>
    );
  }

  return (
    <div className={CONTAINER_CLASS}>
      <div
        role="listbox"
        className="scroll-mask-4 max-h-60 flex-1 scroll-py-8 overflow-y-auto p-1"
        onMouseMove={() => !hasMouseMoved && setHasMouseMoved(true)}
      >
        {items.map((item, index) => (
          <ItemMenuItem
            key={item.id}
            ref={(el) => {
              itemRefs.current[index] = el;
            }}
            size="xs"
            // `option` inside the listbox above, not the `menuitem` this
            // primitive defaults to. Selection is the plugin's, driven by the
            // keys it forwards, so it rides on aria-selected rather than the
            // focus these rows never take (the caret stays in the editor).
            role="option"
            aria-selected={index === selectedIndex}
            onClick={() => command(item)}
            onMouseEnter={() => hasMouseMoved && setSelectedIndex(index)}
            className="w-full text-left aria-selected:bg-fill-selected"
          >
            {renderItem ? renderItem(item) : <DefaultRow item={item} />}
          </ItemMenuItem>
        ))}
      </div>
      <div className="flex items-center gap-1 border-border border-t bg-muted/40 px-2 py-1 text-[11px] text-muted-foreground">
        <Kbd>↑</Kbd>
        <Kbd>↓</Kbd>
        <span>navigate</span>
        <span>·</span>
        <Kbd>↵</Kbd>
        <span>select</span>
        <span>·</span>
        <Kbd>esc</Kbd>
        <span>dismiss</span>
      </div>
    </div>
  );
});

SuggestionList.displayName = "SuggestionList";
