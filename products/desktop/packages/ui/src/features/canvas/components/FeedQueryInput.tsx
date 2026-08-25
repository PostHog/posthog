import {
  type FeedQuerySegment,
  lexFeedQuery,
} from "@posthog/core/tasks/feedQuery";
import { cn, Kbd } from "@posthog/quill";
import {
  FeedQueryMatchedLabel,
  useFeedQuerySuggestions,
} from "@posthog/ui/features/canvas/components/feedQuerySuggestions";
import { applyFeedQuerySuggestion } from "@posthog/ui/features/canvas/components/feedQuerySuggestionUtils";
import {
  Fragment,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

// Keep the input and syntax mirror on the same text metrics.
export const EDITOR_TEXT_CLASS =
  "whitespace-pre font-mono text-[13px] leading-none tracking-normal";

export function FeedQueryHighlight({
  query,
  className,
}: {
  query: string;
  className?: string;
}) {
  const segments = useMemo(() => lexFeedQuery(query), [query]);
  return (
    <span className={cn(EDITOR_TEXT_CLASS, className)}>
      {segments.map((segment) => (
        <Fragment key={segment.start}>{renderSegment(segment)}</Fragment>
      ))}
    </span>
  );
}

function renderSegment(segment: FeedQuerySegment): ReactNode {
  if (segment.kind !== "token" || !segment.token) {
    return <span className="text-(--gray-12)">{segment.raw}</span>;
  }
  const { token, raw } = segment;
  const negPrefix = raw.startsWith("-") ? "-" : "";
  const rest = raw.slice(negPrefix.length);
  const colon = rest.indexOf(":");
  const keyText = rest.slice(0, colon + 1);
  let valueText = rest.slice(colon + 1);
  let notPrefix = "";
  if (valueText.toLowerCase().startsWith("not:")) {
    notPrefix = valueText.slice(0, 4);
    valueText = valueText.slice(4);
  }
  const negated = token.negated;
  return (
    <span
      className={cn(
        "rounded-[3px]",
        negated ? "bg-(--red-a3)" : "bg-(--gray-a3)",
      )}
    >
      {negPrefix && <span className="text-(--red-11)">{negPrefix}</span>}
      <span className={negated ? "text-(--red-11)" : "text-(--blue-11)"}>
        {keyText}
      </span>
      {notPrefix && <span className="text-(--red-11)">{notPrefix}</span>}
      <span
        className={cn(
          token.invalid
            ? "text-(--red-11) underline decoration-(--red-8) decoration-wavy underline-offset-2"
            : token.unsupported
              ? "text-(--amber-11) underline decoration-(--amber-8) decoration-dotted underline-offset-2"
              : negated
                ? "text-(--red-12)"
                : "text-(--gray-12)",
        )}
      >
        {valueText}
      </span>
    </span>
  );
}

export function FeedQueryInput({
  id,
  value,
  onChange,
  onSubmit,
  placeholder,
  autoFocus,
  openOnFocus = true,
  "aria-label": ariaLabel,
}: {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  onSubmit?: () => void;
  placeholder?: string;
  autoFocus?: boolean;
  openOnFocus?: boolean;
  "aria-label"?: string;
}) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const listboxId = `${inputId}-suggestions`;
  const inputRef = useRef<HTMLInputElement>(null);
  const mirrorRef = useRef<HTMLDivElement>(null);
  const [caret, setCaret] = useState(0);
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(0);

  // Restore the caret after React applies a completed suggestion.
  const pendingCaret = useRef<number | null>(null);
  useLayoutEffect(() => {
    if (pendingCaret.current == null) return;
    inputRef.current?.setSelectionRange(
      pendingCaret.current,
      pendingCaret.current,
    );
    inputRef.current?.focus();
    pendingCaret.current = null;
  });

  // Keep the syntax mirror aligned with a horizontally scrolled input.
  const syncScroll = () => {
    if (mirrorRef.current && inputRef.current) {
      mirrorRef.current.scrollLeft = inputRef.current.scrollLeft;
    }
  };
  useLayoutEffect(syncScroll);

  const { group, context } = useFeedQuerySuggestions(value, caret);
  const suggestions = group.items;
  const visible = open && suggestions.length > 0;
  const highlightedIndex = Math.min(highlighted, suggestions.length - 1);

  const apply = (suggestion: (typeof suggestions)[number]) => {
    const edit = applyFeedQuerySuggestion(value, context, suggestion);
    onChange(edit.next);
    setCaret(edit.caret);
    pendingCaret.current = edit.caret;
    setHighlighted(0);
    setOpen(edit.completedKey);
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.nativeEvent.isComposing) return;
    if (visible) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setHighlighted((h) => (h + 1) % suggestions.length);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setHighlighted(
          (h) => (h - 1 + suggestions.length) % suggestions.length,
        );
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        event.preventDefault();
        apply(suggestions[highlightedIndex]);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        setOpen(false);
        return;
      }
    }
    if (event.key === "Enter") {
      event.preventDefault();
      onSubmit?.();
    }
  };

  const trackCaret = () => {
    const position = inputRef.current?.selectionStart;
    if (position != null) setCaret(position);
  };

  return (
    <div className="relative">
      <div
        className={cn(
          "relative h-9 overflow-hidden rounded-md border border-(--gray-a7) bg-(--color-surface)",
          "focus-within:-outline-offset-1 focus-within:outline focus-within:outline-(--focus-8) focus-within:outline-2",
        )}
      >
        <div
          ref={mirrorRef}
          aria-hidden
          className={cn(
            "pointer-events-none absolute inset-0 flex items-center overflow-x-hidden px-2.5",
            EDITOR_TEXT_CLASS,
          )}
        >
          <FeedQueryHighlight query={value} />
        </div>
        <input
          ref={inputRef}
          id={inputId}
          role="combobox"
          aria-label={ariaLabel}
          aria-autocomplete="list"
          aria-expanded={visible}
          aria-controls={visible ? listboxId : undefined}
          aria-activedescendant={
            visible ? `${listboxId}-${highlightedIndex}` : undefined
          }
          type="text"
          value={value}
          placeholder={placeholder}
          autoComplete="off"
          // biome-ignore lint/a11y/noAutofocus: the modal opens to type a query
          autoFocus={autoFocus}
          autoCorrect="off"
          autoCapitalize="off"
          spellCheck={false}
          className={cn(
            "absolute inset-0 w-full bg-transparent px-2.5 outline-none",
            EDITOR_TEXT_CLASS,
            "text-transparent caret-(--gray-12) placeholder:text-(--gray-9)",
            "selection:bg-(--blue-a4) selection:text-transparent",
          )}
          onChange={(e) => {
            onChange(e.target.value);
            setOpen(true);
            setHighlighted(0);
            trackCaret();
          }}
          onScroll={syncScroll}
          onClick={() => setOpen(true)}
          onSelect={trackCaret}
          onKeyDown={onKeyDown}
          onFocus={() => {
            if (openOnFocus) setOpen(true);
          }}
          onBlur={() => setTimeout(() => setOpen(false), 120)}
        />
      </div>
      {visible && (
        <div className="absolute top-full right-0 left-0 z-50 mt-1.5 overflow-hidden rounded-lg border border-border bg-card shadow-lg">
          {group.heading !== "" && (
            <div className="px-3 pt-2 pb-1 font-medium text-(--gray-9) text-[11px] uppercase tracking-wider">
              {group.heading}
            </div>
          )}
          <div
            id={listboxId}
            role="listbox"
            aria-label="Query suggestions"
            className="max-h-60 overflow-y-auto px-1 pb-1"
          >
            {suggestions.map((suggestion, index) => (
              <button
                id={`${listboxId}-${index}`}
                key={`${context.activeKey ?? "key"}:${suggestion.label}`}
                type="button"
                role="option"
                aria-selected={index === highlightedIndex}
                className={cn(
                  "flex h-7 w-full items-center gap-2 rounded-md px-2 text-left text-[13px]",
                  index === highlightedIndex
                    ? "bg-fill-hover text-foreground"
                    : "text-(--gray-11)",
                )}
                onMouseDown={(e) => e.preventDefault()}
                onMouseEnter={() => setHighlighted(index)}
                onClick={() => apply(suggestion)}
              >
                {suggestion.icon}
                <FeedQueryMatchedLabel
                  label={suggestion.label}
                  typed={context.typed}
                />
                {suggestion.hint && (
                  <span className="min-w-0 flex-1 truncate text-right text-(--gray-9) text-xs">
                    {suggestion.hint}
                  </span>
                )}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2 border-(--gray-a5) border-t px-3 py-1.5 text-(--gray-9) text-xs">
            <Kbd>↑↓</Kbd> navigate
            <Kbd>⏎</Kbd> select
            <Kbd>tab</Kbd> complete
          </div>
        </div>
      )}
    </div>
  );
}
