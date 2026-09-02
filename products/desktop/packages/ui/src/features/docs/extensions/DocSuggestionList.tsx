import { Kbd } from "@posthog/quill";
import type { SuggestionItem } from "@posthog/ui/features/message-editor/types";
import {
  forwardRef,
  type ReactNode,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";

export interface DocSuggestionListRef {
  onKeyDown: (props: { event: KeyboardEvent }) => boolean;
}

/** A doc typeahead row: what the base item has, plus a glyph and a section. */
export interface DocSuggestionItem extends SuggestionItem {
  icon?: ReactNode;
  group?: string;
  /** A short hint at the row's end: a shortcut, a kind, a count. */
  hint?: string;
}

interface Props {
  items: DocSuggestionItem[];
  command: (item: DocSuggestionItem) => void;
  loading?: boolean;
  emptyMessage?: string;
}

/**
 * The popup under `/`, `+`, and `@` in a doc.
 *
 * One line per row: a glyph, the name, and what it does in fewer words, so ten
 * choices fit without a scrollbar and the eye finds one by its shape. Groups
 * carry a small label; the keys are said once, quietly, at the bottom.
 */
export const DocSuggestionList = forwardRef<DocSuggestionListRef, Props>(
  (
    { items, command, loading = false, emptyMessage = "Nothing matches" },
    ref,
  ) => {
    const [selectedIndex, setSelectedIndex] = useState(0);
    const rowRefs = useRef<(HTMLButtonElement | null)[]>([]);
    const [pointerMoved, setPointerMoved] = useState(false);
    const previousItems = useRef(items);

    if (previousItems.current !== items) {
      previousItems.current = items;
      setSelectedIndex(0);
      setPointerMoved(false);
    }

    // biome-ignore lint/correctness/useExhaustiveDependencies: the row list changes with the items
    useEffect(() => {
      rowRefs.current[selectedIndex]?.scrollIntoView({ block: "nearest" });
    }, [selectedIndex, items]);

    useImperativeHandle(ref, () => ({
      onKeyDown: ({ event }) => {
        if (items.length === 0) return false;
        if (event.key === "ArrowUp") {
          setSelectedIndex((i) => (i + items.length - 1) % items.length);
          return true;
        }
        if (event.key === "ArrowDown") {
          setSelectedIndex((i) => (i + 1) % items.length);
          return true;
        }
        if (event.key === "Enter" || event.key === "Tab") {
          const item = items[selectedIndex];
          if (!item) return false;
          command(item);
          return true;
        }
        return false;
      },
    }));

    return (
      <div className="doc-suggest">
        {items.length === 0 ? (
          <div className="doc-suggest-empty">
            {loading ? "Looking…" : emptyMessage}
          </div>
        ) : (
          <div
            role="listbox"
            className="doc-suggest-list"
            onMouseMove={() => !pointerMoved && setPointerMoved(true)}
          >
            {items.map((item, index) => {
              const newGroup =
                item.group && item.group !== items[index - 1]?.group;
              return (
                <div key={item.id} className="contents">
                  {newGroup ? (
                    <div className="doc-suggest-group">{item.group}</div>
                  ) : null}
                  <button
                    type="button"
                    role="option"
                    aria-selected={index === selectedIndex}
                    ref={(el) => {
                      rowRefs.current[index] = el;
                    }}
                    // The caret stays in the editor; a press must not take it.
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => command(item)}
                    onMouseEnter={() => pointerMoved && setSelectedIndex(index)}
                    className="doc-suggest-row"
                  >
                    <span className="doc-suggest-icon">{item.icon}</span>
                    <span className="doc-suggest-label">{item.label}</span>
                    {item.description ? (
                      <span className="doc-suggest-desc">
                        {item.description}
                      </span>
                    ) : null}
                    {item.hint ? (
                      <span className="doc-suggest-hint">{item.hint}</span>
                    ) : null}
                  </button>
                </div>
              );
            })}
          </div>
        )}
        <div className="doc-suggest-keys">
          <Kbd>↑</Kbd>
          <Kbd>↓</Kbd>
          <Kbd>↵</Kbd>
          <span>{loading ? "looking…" : "esc to close"}</span>
        </div>
      </div>
    );
  },
);

DocSuggestionList.displayName = "DocSuggestionList";
