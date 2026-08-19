import {
  ArchiveIcon,
  AtIcon,
  CheckCircleIcon,
  CircleHalfIcon,
  GitMergeIcon,
  GitPullRequestIcon,
  HashIcon,
  PackageIcon,
  PencilSimpleIcon,
  UserCircleIcon,
  XIcon,
} from "@phosphor-icons/react";
import {
  type FeedQuerySegment,
  lexFeedQuery,
  TASK_RUN_STATUSES,
} from "@posthog/core/tasks/feedQuery";
import { cn, Kbd } from "@posthog/quill";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { DOT_TONE_VAR } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import {
  Fragment,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
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
  icon?: ReactNode;
}

/** What the open dropdown is offering, with the heading that says so. */
interface SuggestionGroup {
  heading: string;
  items: Suggestion[];
}

function keyIcon(icon: ReactNode): ReactNode {
  return (
    <span className="flex size-4 items-center justify-center text-(--gray-9)">
      {icon}
    </span>
  );
}

const KEY_SUGGESTIONS: Suggestion[] = [
  {
    insert: "created-by:",
    label: "created-by:",
    hint: "who started the task",
    icon: keyIcon(<UserCircleIcon size={14} />),
  },
  {
    insert: "space:",
    label: "space:",
    hint: "tasks filed to a space",
    icon: keyIcon(<HashIcon size={14} />),
  },
  {
    insert: "repo:",
    label: "repo:",
    hint: "repository the task targets",
    icon: keyIcon(<PackageIcon size={14} />),
  },
  {
    insert: "status:",
    label: "status:",
    hint: "latest run status",
    icon: keyIcon(<CircleHalfIcon size={14} />),
  },
  {
    insert: "is:",
    label: "is:",
    hint: "archived, running, done, failed",
    icon: keyIcon(<ArchiveIcon size={14} />),
  },
  {
    insert: "origin:",
    label: "origin:",
    hint: "product that created the task",
    icon: keyIcon(<AtIcon size={14} />),
  },
  {
    insert: "pr:",
    label: "pr:",
    hint: "any, none, open, draft, merged, closed",
    icon: keyIcon(<GitPullRequestIcon size={14} />),
  },
  {
    insert: "ci:",
    label: "ci:",
    hint: "failing, passing, pending",
    icon: keyIcon(<CheckCircleIcon size={14} />),
  },
];

const IS_VALUES = ["archived", "running", "done", "failed"];

const PR_SUGGESTIONS: Suggestion[] = [
  {
    insert: "any",
    label: "any",
    hint: "has a pull request",
    icon: keyIcon(<GitPullRequestIcon size={14} />),
  },
  {
    insert: "none",
    label: "none",
    hint: "no pull request",
    icon: keyIcon(<XIcon size={14} />),
  },
  {
    insert: "open",
    label: "open",
    hint: "PR open for review",
    icon: keyIcon(<GitPullRequestIcon size={14} />),
  },
  {
    insert: "draft",
    label: "draft",
    hint: "PR still a draft",
    icon: keyIcon(<PencilSimpleIcon size={14} />),
  },
  {
    insert: "merged",
    label: "merged",
    hint: "PR merged",
    icon: keyIcon(<GitMergeIcon size={14} />),
  },
  {
    insert: "closed",
    label: "closed",
    hint: "PR closed without merging",
    icon: keyIcon(<XIcon size={14} />),
  },
];

/** Canonical first; the red/green spellings parse but aren't offered. */
const CI_SUGGESTED_VALUES = ["failing", "passing", "pending"];

const CI_DOT_TONE: Record<string, string> = {
  failing: DOT_TONE_VAR.red,
  passing: DOT_TONE_VAR.green,
  pending: DOT_TONE_VAR.yellow,
};

const STATUS_DOT_TONE: Record<string, string> = {
  failed: DOT_TONE_VAR.red,
  in_progress: DOT_TONE_VAR.blue,
  completed: DOT_TONE_VAR.green,
  queued: DOT_TONE_VAR.yellow,
  cancelled: DOT_TONE_VAR.gray,
  not_started: DOT_TONE_VAR.gray,
};

function statusDot(status: string): ReactNode {
  return (
    <span className="flex size-4 items-center justify-center">
      <span
        className="size-2 rounded-full"
        style={{
          backgroundColor: STATUS_DOT_TONE[status] ?? DOT_TONE_VAR.gray,
        }}
      />
    </span>
  );
}

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

/** Bolds the typed prefix inside a suggestion's label. */
function MatchedLabel({ label, typed }: { label: string; typed: string }) {
  const matches =
    typed !== "" && label.toLowerCase().startsWith(typed.toLowerCase());
  if (!matches) return <span className="font-medium">{label}</span>;
  return (
    <span>
      <span className="font-semibold text-foreground">
        {label.slice(0, typed.length)}
      </span>
      <span className="font-medium">{label.slice(typed.length)}</span>
    </span>
  );
}

// The mirror and the input must lay glyphs out identically, so everything that
// affects metrics lives in this one string: same font, size, tracking. Mono on
// purpose — it reads as a query language and keeps the overlay exact.
const EDITOR_TEXT_CLASS =
  "whitespace-pre font-mono text-[13px] leading-none tracking-normal";

/**
 * A query string rendered with inline syntax coloring, from the same lexer the
 * parser uses: tokens get a tinted pill, negation reads red, a value the
 * parser rejects gets a wavy underline, a not-yet-supported one a dotted amber
 * underline. Doubles as the editor's mirror (metrics must match the input
 * exactly, so token styling never changes font or weight) and the feed page's
 * read-only query display.
 */
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
      {segments.map((segment, index) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: segments are positional slices of the string
        <Fragment key={index}>{renderSegment(segment)}</Fragment>
      ))}
    </span>
  );
}

function renderSegment(segment: FeedQuerySegment): ReactNode {
  if (segment.kind !== "token" || !segment.token) {
    return <span className="text-(--gray-12)">{segment.raw}</span>;
  }
  const { token, raw } = segment;
  // Re-slice the raw chunk so the mirror renders exactly what was typed
  // (alias spellings, quotes, `not:`) with color boundaries at the pieces.
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

/**
 * The feed query editor. The input's own text is transparent; an exactly
 * aligned mirror underneath draws it with inline syntax coloring, so the query
 * is highlighted as it is typed — no separate preview row, nothing below the
 * field appearing and disappearing.
 *
 * Suggestions float in a popup anchored under the field, sized to what they
 * are: the filter catalog on focus, a key's values (teammates, spaces, repos,
 * statuses) while editing a token — applied with ⏎ or Tab — and nothing at
 * all while typing free text, which is just a search term. The host dialog
 * must not clip overflow, or the popup gets cut at the dialog's edge.
 */
export function FeedQueryInput({
  id,
  value,
  onChange,
  onSubmit,
  placeholder,
  autoFocus,
  "aria-label": ariaLabel,
}: {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  /** Called on Enter while no suggestion is highlighted. */
  onSubmit?: () => void;
  placeholder?: string;
  autoFocus?: boolean;
  "aria-label"?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const mirrorRef = useRef<HTMLDivElement>(null);
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

  // The mirror scrolls with the input, or long queries would shear apart.
  const syncScroll = () => {
    if (mirrorRef.current && inputRef.current) {
      mirrorRef.current.scrollLeft = inputRef.current.scrollLeft;
    }
  };
  useLayoutEffect(syncScroll);

  // Value providers for the data-backed keys.
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
  const typed = activeKey === null ? bare : activeValue;

  const group = useMemo<SuggestionGroup>(() => {
    const startsWith = (candidate: string) =>
      candidate.toLowerCase().startsWith(activeValue.toLowerCase());
    switch (activeKey) {
      case null: {
        const prefix = bare.toLowerCase();
        return {
          heading: "Filters",
          items: KEY_SUGGESTIONS.filter((s) => s.label.startsWith(prefix)),
        };
      }
      case "created-by":
      case "author":
      case "by": {
        const me: Suggestion[] = startsWith("@me")
          ? [
              {
                insert: "@me",
                label: "@me",
                hint: "you",
                icon: keyIcon(<UserCircleIcon size={14} />),
              },
            ]
          : [];
        const matches = members
          .filter(
            (member) =>
              startsWith(userDisplayName(member)) || startsWith(member.email),
          )
          .slice(0, 8);
        return {
          heading: "Teammates",
          items: [
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
                icon: <UserAvatar user={member} size="xs" />,
              };
            }),
          ],
        };
      }
      case "space":
      case "channel":
        return {
          heading: "Spaces",
          items: channels
            .filter((c) => startsWith(c.name))
            .slice(0, 8)
            .map((c) => ({
              insert: c.name,
              label: c.name,
              icon: keyIcon(<HashIcon size={14} />),
            })),
        };
      case "repo":
      case "repository":
        return {
          heading: "Repositories",
          items: repositories
            .filter(startsWith)
            .slice(0, 8)
            .map((repo) => ({
              insert: repo,
              label: repo,
              icon: keyIcon(<PackageIcon size={14} />),
            })),
        };
      case "status":
        return {
          heading: "Run status",
          items: TASK_RUN_STATUSES.filter(startsWith).map((status) => ({
            insert: status,
            label: status,
            icon: statusDot(status),
          })),
        };
      case "is":
        return {
          heading: "Task state",
          items: IS_VALUES.filter(startsWith).map((v) => ({
            insert: v,
            label: v,
            icon:
              v === "archived"
                ? keyIcon(<ArchiveIcon size={14} />)
                : statusDot(
                    v === "running"
                      ? "in_progress"
                      : v === "done"
                        ? "completed"
                        : "failed",
                  ),
          })),
        };
      case "pr":
        return {
          heading: "Pull request",
          items: PR_SUGGESTIONS.filter((s) => startsWith(s.label)),
        };
      case "ci":
        return {
          heading: "CI checks",
          items: CI_SUGGESTED_VALUES.filter(startsWith).map((v) => ({
            insert: v,
            label: v,
            icon: (
              <span className="flex size-4 items-center justify-center">
                <span
                  className="size-2 rounded-full"
                  style={{ backgroundColor: CI_DOT_TONE[v] }}
                />
              </span>
            ),
          })),
        };
      default:
        return { heading: "", items: [] };
    }
  }, [activeKey, activeValue, bare, members, channels, repositories]);

  const suggestions = group.items;
  // The dropdown only exists while it has something to offer: focused, with
  // suggestions for the chunk under the caret. Free text mid-word matches no
  // key, so typing a search term shows no dropdown at all.
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
      {/* The field: mirror below, transparent-text input above. Both carry
          identical typography and padding, so the native caret and selection
          sit exactly on the colored text. */}
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
          id={id}
          aria-label={ariaLabel}
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
          onSelect={trackCaret}
          onKeyDown={onKeyDown}
          onFocus={() => setOpen(true)}
          // Delayed so a mousedown on a suggestion lands before the list goes.
          onBlur={() => setTimeout(() => setOpen(false), 120)}
        />
      </div>
      {/* Anchored under the field and sized to its contents, like an editor's
          completion popup — a reserved panel left a wall of dead space around
          one or two rows. The dialog that hosts this must not clip overflow
          (see TaskFeedModal); everything else about the layout stays put
          because the popup floats. */}
      {visible && (
        <div className="absolute top-full right-0 left-0 z-50 mt-1.5 overflow-hidden rounded-lg border border-(--gray-a6) bg-(--color-panel-solid) shadow-lg">
          {group.heading !== "" && (
            <div className="px-3 pt-2 pb-1 font-medium text-(--gray-9) text-[11px] uppercase tracking-wider">
              {group.heading}
            </div>
          )}
          <div
            role="listbox"
            aria-label="Query suggestions"
            className="max-h-60 overflow-y-auto px-1 pb-1"
          >
            {suggestions.map((suggestion, index) => (
              <button
                key={`${activeKey ?? "key"}:${suggestion.label}`}
                type="button"
                role="option"
                aria-selected={index === highlightedIndex}
                className={cn(
                  "flex h-7 w-full items-center gap-2 rounded-md px-2 text-left text-[13px]",
                  index === highlightedIndex
                    ? "bg-fill-hover text-foreground"
                    : "text-(--gray-11)",
                )}
                // Before blur, so picking a row doesn't close the list first.
                onMouseDown={(e) => e.preventDefault()}
                onMouseEnter={() => setHighlighted(index)}
                onClick={() => apply(suggestion)}
              >
                {suggestion.icon}
                <MatchedLabel label={suggestion.label} typed={typed} />
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
