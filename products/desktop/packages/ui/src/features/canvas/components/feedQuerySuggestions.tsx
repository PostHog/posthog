import {
  AppWindowIcon,
  ArchiveIcon,
  AtIcon,
  ChatCircleIcon,
  CheckCircleIcon,
  CircleHalfIcon,
  GitMergeIcon,
  GitPullRequestIcon,
  HashIcon,
  MagnifyingGlassIcon,
  PackageIcon,
  PencilSimpleIcon,
  PushPinIcon,
  SquaresFourIcon,
  UserCircleIcon,
  UsersIcon,
  XIcon,
} from "@phosphor-icons/react";
import { TASK_RUN_STATUSES } from "@posthog/core/tasks/feedQuery";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { getOriginProductMeta } from "@posthog/ui/features/sidebar/components/items/TaskIcon";
import { DOT_TONE_VAR } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { type ReactNode, useMemo } from "react";

/** One row of the query autocomplete: what gets inserted, and why you'd pick it. */
export interface FeedQuerySuggestion {
  /** Inserted into the query. A key suggestion ends with ":" and keeps the
   * completion open for its values; a value suggestion completes the token. */
  insert: string;
  label: string;
  hint?: string;
  icon?: ReactNode;
}

/** What the completion is offering, with the heading that says so. */
export interface FeedQuerySuggestionGroup {
  heading: string;
  items: FeedQuerySuggestion[];
}

/** The chunk of text the caret is inside, and what the caret is editing. */
export interface FeedQueryEditContext {
  chunk: { start: number; end: number; text: string };
  /** The filter key being valued, or null while typing a key / free text. */
  activeKey: string | null;
  /** What the highlighter should bold: the key prefix or the value so far. */
  typed: string;
}

function keyIcon(icon: ReactNode): ReactNode {
  return (
    <span className="flex size-4 items-center justify-center text-(--gray-9)">
      {icon}
    </span>
  );
}

const KEY_SUGGESTIONS: FeedQuerySuggestion[] = [
  {
    insert: "created-by:",
    label: "created-by:",
    hint: "who started the task",
    icon: keyIcon(<UserCircleIcon size={14} />),
  },
  {
    insert: "commented-by:",
    label: "commented-by:",
    hint: "who commented on the thread",
    icon: keyIcon(<ChatCircleIcon size={14} />),
  },
  {
    insert: "mentions:",
    label: "mentions:",
    hint: "who the thread mentions",
    icon: keyIcon(<AtIcon size={14} />),
  },
  {
    insert: "involves:",
    label: "involves:",
    hint: "started or commented",
    icon: keyIcon(<UsersIcon size={14} />),
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
    hint: "archived, pinned, running, done, failed",
    icon: keyIcon(<ArchiveIcon size={14} />),
  },
  {
    insert: "origin:",
    label: "origin:",
    hint: "slack, scout, desktop, ai…",
    icon: keyIcon(<AppWindowIcon size={14} />),
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

/** Only offered where results have kinds to scope (the command palette). */
const PALETTE_KEY_SUGGESTIONS: FeedQuerySuggestion[] = [
  {
    insert: "type:",
    label: "type:",
    hint: "task, space, command, saved",
    icon: keyIcon(<SquaresFourIcon size={14} />),
  },
  {
    insert: "saved:",
    label: "saved:",
    hint: "open a saved search",
    icon: keyIcon(<MagnifyingGlassIcon size={14} />),
  },
];

const TYPE_VALUES: FeedQuerySuggestion[] = [
  { insert: "task", label: "task", hint: "only tasks" },
  { insert: "space", label: "space", hint: "only spaces" },
  { insert: "command", label: "command", hint: "only commands" },
  { insert: "saved", label: "saved", hint: "only saved searches" },
].map((s) => ({ ...s, icon: keyIcon(<SquaresFourIcon size={14} />) }));

const IS_VALUES = ["archived", "pinned", "running", "done", "failed"];

// The backend's `Task.OriginProduct` enum, most-reached-for first. Hints
// carry the branded label where the sidebar has one (`getOriginProductMeta`)
// so the same origin reads the same everywhere; the rest are spelled out
// here. `origin:desktop`, `origin:scout`, … alias onto these in the planner.
const ORIGIN_VALUES: { value: string; fallbackHint: string }[] = [
  { value: "user_created", fallbackHint: "you, from desktop or the app" },
  { value: "slack", fallbackHint: "Slack" },
  { value: "signals_scout", fallbackHint: "Signals scout" },
  { value: "posthog_ai", fallbackHint: "PostHog AI" },
  { value: "signal_report", fallbackHint: "Signals" },
  { value: "error_tracking", fallbackHint: "Error tracking" },
  { value: "session_summaries", fallbackHint: "Session summary" },
  { value: "loop", fallbackHint: "Loops" },
  { value: "automation", fallbackHint: "Automation" },
  { value: "review_hog", fallbackHint: "ReviewHog" },
  { value: "support_queue", fallbackHint: "Support" },
  { value: "support_reply", fallbackHint: "Support reply" },
  { value: "eval_clusters", fallbackHint: "Evals" },
  { value: "experiments", fallbackHint: "Experiments" },
  { value: "onboarding", fallbackHint: "Onboarding" },
  { value: "hogdesk", fallbackHint: "HogDesk" },
  { value: "mcp_analytics", fallbackHint: "MCP analytics" },
  { value: "signals_chat", fallbackHint: "Signals chat" },
  { value: "image_builder", fallbackHint: "Image builder" },
];

const PR_SUGGESTIONS: FeedQuerySuggestion[] = [
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
export function FeedQueryMatchedLabel({
  label,
  typed,
}: {
  label: string;
  typed: string;
}) {
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

/**
 * What a suggestion does to the query when applied: the rewritten text and
 * where the caret lands. A key completion stays in the token (its values come
 * next); a value completion closes it with a trailing space.
 */
export function applyFeedQuerySuggestion(
  value: string,
  context: FeedQueryEditContext,
  suggestion: FeedQuerySuggestion,
): { next: string; caret: number; completedKey: boolean } {
  const negation = context.chunk.text.startsWith("-") ? "-" : "";
  const isKey = context.activeKey === null;
  const replacement = isKey
    ? `${negation}${suggestion.insert}`
    : `${negation}${context.activeKey}:${quoteIfNeeded(suggestion.insert)} `;
  const next =
    value.slice(0, context.chunk.start) +
    replacement +
    value.slice(context.chunk.end);
  return {
    next,
    caret: context.chunk.start + replacement.length,
    completedKey: isKey,
  };
}

/**
 * The query language's completion brain, shared by the feed modal's editor
 * and the command palette: given the text and the caret, what should be
 * offered — filter keys while typing a bare word, a key's values (teammates,
 * spaces, repos, statuses, …) while inside a token.
 */
export function useFeedQuerySuggestions(
  value: string,
  caret: number,
  options?: { includeType?: boolean },
): { group: FeedQuerySuggestionGroup; context: FeedQueryEditContext } {
  const includeType = options?.includeType ?? false;

  // Value providers for the data-backed keys.
  const { members } = useOrgMembers();
  const { channels } = useChannels();
  const repositories = useMemo(
    () => [...new Set(channels.flatMap((c) => c.repositories ?? []))].sort(),
    [channels],
  );

  const chunk = useMemo(() => chunkAt(value, caret), [value, caret]);
  const bare = chunk.text.replace(/^-/, "");
  const colon = bare.indexOf(":");
  const activeKey = colon === -1 ? null : bare.slice(0, colon).toLowerCase();
  const activeValue =
    colon === -1 ? "" : bare.slice(colon + 1).replace(/^not:/i, "");
  const typed = activeKey === null ? bare : activeValue;

  const group = useMemo<FeedQuerySuggestionGroup>(() => {
    const startsWith = (candidate: string) =>
      candidate.toLowerCase().startsWith(activeValue.toLowerCase());
    switch (activeKey) {
      case null: {
        const prefix = bare.toLowerCase();
        const keys = includeType
          ? [...KEY_SUGGESTIONS, ...PALETTE_KEY_SUGGESTIONS]
          : KEY_SUGGESTIONS;
        return {
          heading: "Filters",
          items: keys.filter((s) => s.label.startsWith(prefix)),
        };
      }
      case "created-by":
      case "author":
      case "by":
      case "commented-by":
      case "commenter":
      case "mentions":
      case "mentioned":
      case "involves": {
        const me: FeedQuerySuggestion[] = startsWith("@me")
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
      case "origin": {
        const needle = activeValue.toLowerCase();
        return {
          heading: "Origin",
          items: ORIGIN_VALUES.filter(({ value: v, fallbackHint }) => {
            const hint = getOriginProductMeta(v)?.label ?? fallbackHint;
            return (
              v.startsWith(needle) || hint.toLowerCase().startsWith(needle)
            );
          })
            .slice(0, 8)
            .map(({ value: v, fallbackHint }) => {
              const meta = getOriginProductMeta(v);
              return {
                insert: v,
                label: v,
                hint: meta?.label ?? fallbackHint,
                icon: meta
                  ? keyIcon(<meta.Icon size={14} />)
                  : keyIcon(<AppWindowIcon size={14} />),
              };
            }),
        };
      }
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
                : v === "pinned"
                  ? keyIcon(<PushPinIcon size={14} />)
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
      case "type": {
        if (!includeType) return { heading: "", items: [] };
        return {
          heading: "Result type",
          items: TYPE_VALUES.filter((s) => startsWith(s.label)),
        };
      }
      default:
        return { heading: "", items: [] };
    }
  }, [
    activeKey,
    activeValue,
    bare,
    members,
    channels,
    repositories,
    includeType,
  ]);

  return { group, context: { chunk, activeKey, typed } };
}
