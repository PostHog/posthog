import { FolderIcon } from "@phosphor-icons/react";
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemMedia,
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

const CONTAINER_CLASS =
  "flex w-max min-w-[300px] max-w-[440px] flex-col overflow-hidden rounded-md border border-[var(--gray-a6)] bg-[var(--color-panel-solid)] text-[13px] shadow-lg";

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
      <ItemContent variant="menuItem">
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
        className="max-h-60 flex-1 overflow-y-auto [&::-webkit-scrollbar]:hidden"
        onMouseMove={() => !hasMouseMoved && setHasMouseMoved(true)}
      >
        {items.map((item, index) => {
          const isSelected = index === selectedIndex;
          return (
            <button
              type="button"
              key={item.id}
              ref={(el) => {
                itemRefs.current[index] = el;
              }}
              onClick={() => command(item)}
              onMouseEnter={() => hasMouseMoved && setSelectedIndex(index)}
              className={`flex w-full border-none px-2 py-0.5 text-left ${
                isSelected ? "bg-[var(--accent-a4)]" : ""
              }`}
            >
              {renderItem ? renderItem(item) : <DefaultRow item={item} />}
            </button>
          );
        })}
      </div>
      <div className="flex items-center gap-1 border-[var(--gray-a4)] border-t bg-[var(--gray-a2)] px-2 py-1 text-[11px] text-[var(--gray-10)]">
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
