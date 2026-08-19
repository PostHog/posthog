import { WarningCircleIcon } from "@phosphor-icons/react";
import {
  type FeedQueryIssue,
  parseFeedQuery,
  TASK_RUN_STATUSES,
} from "@posthog/core/tasks/feedQuery";
import { cn } from "@posthog/quill";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { TextField } from "@radix-ui/themes";
import {
  type KeyboardEvent as ReactKeyboardEvent,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

/** One row of the autocomplete: what gets inserted, and why you'd pick it. */
interface Suggestion {
  /** Inserted into the query. A key suggestion ends with ":" and keeps the
   * dropdown open for its values; a value suggestion completes the token. */
  insert: string;
  label: string;
  hint?: string;
}

const KEY_SUGGESTIONS: Suggestion[] = [
  { insert: "created-by:", label: "created-by:", hint: "who started the task" },
  { insert: "space:", label: "space:", hint: "tasks filed to a space" },
  { insert: "repo:", label: "repo:", hint: "repository the task targets" },
  { insert: "status:", label: "status:", hint: "latest run status" },
  { insert: "is:", label: "is:", hint: "archived, running, done, failed" },
  {
    insert: "origin:",
    label: "origin:",
    hint: "product that created the task",
  },
  { insert: "pr:", label: "pr:", hint: "any, none" },
];

const IS_VALUES = ["archived", "running", "done", "failed"];
const PR_SUGGESTED_VALUES = ["any", "none"];

// The chunk under the caret: the run of non-space characters around it. Quoted
// values with spaces come from suggestion insertion, which moves the caret past
// them, so the editing chunk itself never needs quote awareness.
function chunkAt(
  value: string,
  caret: number,
): { start: number; end: number; text: string } {
  let start = caret;
  while (start > 0 && !/\s/.test(value[start - 1])) start--;
  let end = caret;
  while (end < value.length && !/\s/.test(value[end])) end++;
  return { start, end, text: value.slice(start, end) };
}

function quoteIfNeeded(value: string): string {
  return /\s/.test(value) ? `"${value}"` : value;
}

/**
 * The feed query editor: a plain text input with GitHub-style token
 * autocomplete. Typing suggests filter keys; after `created-by:` it suggests
 * teammates, after `space:` your spaces, and so on. The parsed tokens and any
 * problems render as chips below, so a typo is visible before it is saved.
 */
export function FeedQueryInput({
  id,
  value,
  onChange,
  onSubmit,
  autoFocus,
  placeholder,
  "aria-label": ariaLabel,
}: {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  /** Called on Enter while no suggestion is highlighted. */
  onSubmit?: () => void;
  autoFocus?: boolean;
  placeholder?: string;
  "aria-label"?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [caret, setCaret] = useState(0);
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(0);

  // Where the caret belongs after a completion rewrites the value. Applied in
  // a layout effect (after React committed the new value) rather than a
  // rAF, whose timing races the next keystroke.
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

  // Value providers for the data-backed keys. Loaded lazily-ish: members only
  // once the input is in use (this component only mounts in the feed editor).
  const { members } = useOrgMembers();
  const { channels } = useChannels();
  const repositories = useMemo(
    () => [...new Set(channels.flatMap((c) => c.repositories ?? []))].sort(),
    [channels],
  );

  const chunk = chunkAt(value, caret);
  const bare = chunk.text.replace(/^-/, "");
  const colon = bare.indexOf(":");
  const activeKey = colon === -1 ? null : bare.slice(0, colon).toLowerCase();
  const activeValue =
    colon === -1 ? "" : bare.slice(colon + 1).replace(/^not:/i, "");

  const suggestions = useMemo<Suggestion[]>(() => {
    const startsWith = (candidate: string) =>
      candidate.toLowerCase().startsWith(activeValue.toLowerCase());
    switch (activeKey) {
      case null: {
        const prefix = bare.toLowerCase();
        return KEY_SUGGESTIONS.filter((s) => s.label.startsWith(prefix));
      }
      case "created-by":
      case "author":
      case "by": {
        const me: Suggestion[] = startsWith("@me")
          ? [{ insert: "@me", label: "@me", hint: "you" }]
          : [];
        const matches = members
          .filter(
            (member) =>
              startsWith(userDisplayName(member)) || startsWith(member.email),
          )
          .slice(0, 8);
        return [
          ...me,
          ...matches.map((member) => {
            // Insert the first name where it names one person; fall back to
            // the email's user part so "created-by:sam" can't mean two Sams.
            const first = (member.first_name ?? "").toLowerCase();
            const unique =
              first !== "" &&
              members.filter(
                (m) => (m.first_name ?? "").toLowerCase() === first,
              ).length === 1;
            return {
              insert: unique ? first : member.email.split("@")[0],
              label: userDisplayName(member),
              hint: member.email,
            };
          }),
        ];
      }
      case "space":
      case "channel":
        return channels
          .filter((c) => startsWith(c.name))
          .slice(0, 8)
          .map((c) => ({ insert: c.name, label: c.name }));
      case "repo":
      case "repository":
        return repositories
          .filter(startsWith)
          .slice(0, 8)
          .map((repo) => ({ insert: repo, label: repo }));
      case "status":
        return TASK_RUN_STATUSES.filter(startsWith).map((status) => ({
          insert: status,
          label: status,
        }));
      case "is":
        return IS_VALUES.filter(startsWith).map((v) => ({
          insert: v,
          label: `is:${v}`,
        }));
      case "pr":
        return PR_SUGGESTED_VALUES.filter(startsWith).map((v) => ({
          insert: v,
          label: `pr:${v}`,
          hint: v === "any" ? "has a pull request" : "no pull request",
        }));
      default:
        return [];
    }
  }, [activeKey, activeValue, bare, members, channels, repositories]);

  const visible = open && suggestions.length > 0;
  const highlightedIndex = Math.min(highlighted, suggestions.length - 1);

  const apply = (suggestion: Suggestion) => {
    const negation = chunk.text.startsWith("-") ? "-" : "";
    const isKey = activeKey === null;
    const replacement = isKey
      ? `${negation}${suggestion.insert}`
      : `${negation}${activeKey}:${quoteIfNeeded(suggestion.insert)} `;
    const next =
      value.slice(0, chunk.start) + replacement + value.slice(chunk.end);
    onChange(next);
    const nextCaret = chunk.start + replacement.length;
    setCaret(nextCaret);
    pendingCaret.current = nextCaret;
    setHighlighted(0);
    // A key completion keeps the dropdown open for its values; a value
    // completion is done with the token.
    setOpen(isKey);
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
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
      <TextField.Root
        ref={inputRef}
        id={id}
        aria-label={ariaLabel}
        autoFocus={autoFocus}
        size="3"
        value={value}
        placeholder={placeholder}
        autoComplete="off"
        spellCheck={false}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
          setHighlighted(0);
          trackCaret();
        }}
        onSelect={trackCaret}
        onKeyDown={onKeyDown}
        onFocus={() => setOpen(true)}
        // Delayed so a mousedown on a suggestion lands before the list goes.
        onBlur={() => setTimeout(() => setOpen(false), 120)}
      />
      {visible && (
        <div
          role="listbox"
          aria-label="Query suggestions"
          className="absolute top-full right-0 left-0 z-50 mt-1 max-h-56 overflow-y-auto rounded-md border border-(--gray-6) bg-(--color-panel-solid) p-1 shadow-md"
        >
          {suggestions.map((suggestion, index) => (
            <button
              key={`${activeKey ?? "key"}:${suggestion.label}`}
              type="button"
              role="option"
              aria-selected={index === highlightedIndex}
              className={cn(
                "flex w-full items-baseline gap-2 rounded px-2 py-1 text-left text-sm",
                index === highlightedIndex
                  ? "bg-fill-hover text-foreground"
                  : "text-(--gray-11)",
              )}
              // Before blur, so picking a row doesn't close the list first.
              onMouseDown={(e) => e.preventDefault()}
              onMouseEnter={() => setHighlighted(index)}
              onClick={() => apply(suggestion)}
            >
              <span className="font-medium">{suggestion.label}</span>
              {suggestion.hint && (
                <span className="min-w-0 truncate text-(--gray-9) text-xs">
                  {suggestion.hint}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * The parsed query as chips: one per filter token, plus the free text. Shared
 * by the editor (live preview) and the feed page's query bar, so both surfaces
 * read the query the same way.
 */
export function FeedQueryChips({
  query,
  issues,
  className,
}: {
  query: string;
  /** Resolution issues from the planner; parser issues render regardless. */
  issues?: FeedQueryIssue[];
  className?: string;
}) {
  const parsed = useMemo(() => parseFeedQuery(query), [query]);
  // Planner issues subsume parser issues when the caller passes them.
  const allIssues = issues ?? parsed.issues;
  if (!parsed.text && parsed.tokens.length === 0) return null;
  return (
    <div className={cn("flex min-w-0 flex-col gap-1.5", className)}>
      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
        {parsed.text && (
          <span className="inline-flex h-6 min-w-0 items-center rounded-md border border-(--gray-5) bg-(--gray-3) px-2 text-(--gray-11) text-xs">
            <span className="truncate">&ldquo;{parsed.text}&rdquo;</span>
          </span>
        )}
        {parsed.tokens.map((token, index) => (
          <span
            // biome-ignore lint/suspicious/noArrayIndexKey: tokens are position-identified; duplicates are legal
            key={`${token.raw}-${index}`}
            className={cn(
              "inline-flex h-6 items-center gap-1 rounded-md border px-2 font-medium text-xs",
              token.negated
                ? "border-(--red-6) bg-(--red-3) text-(--red-11)"
                : "border-(--gray-6) bg-(--gray-4) text-(--gray-11)",
            )}
          >
            {token.negated && <span>not</span>}
            <span className="text-(--gray-9)">{token.key}:</span>
            {token.value}
          </span>
        ))}
      </div>
      {allIssues.map((issue) => (
        <div
          key={`${issue.raw}-${issue.message}`}
          className={cn(
            "flex items-center gap-1.5 text-xs",
            issue.kind === "unsupported"
              ? "text-(--amber-11)"
              : "text-(--red-11)",
          )}
        >
          <WarningCircleIcon size={13} className="shrink-0" />
          {issue.message}
        </div>
      ))}
    </div>
  );
}
