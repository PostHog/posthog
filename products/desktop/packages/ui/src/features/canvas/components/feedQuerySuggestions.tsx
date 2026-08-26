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
import type {
  FeedQueryEditContext,
  FeedQuerySuggestion,
} from "@posthog/ui/features/canvas/components/feedQuerySuggestionUtils";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { getOriginProductMeta } from "@posthog/ui/features/sidebar/components/items/TaskIcon";
import { DOT_TONE_VAR } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { type ReactNode, useMemo } from "react";

interface FeedQuerySuggestionGroup {
  heading: string;
  items: FeedQuerySuggestion[];
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
    hint: "task creator or commenter",
    icon: keyIcon(<UsersIcon size={14} />),
  },
  {
    insert: "space:",
    label: "space:",
    hint: "tasks in a space",
    icon: keyIcon(<HashIcon size={14} />),
  },
  {
    insert: "repo:",
    label: "repo:",
    hint: "task repository",
    icon: keyIcon(<PackageIcon size={14} />),
  },
  {
    insert: "status:",
    label: "status:",
    hint: "task's latest run",
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
    hint: "where the task came from",
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
    hint: "open saved searches",
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

export function useFeedQuerySuggestions(
  value: string,
  caret: number,
  options?: { includeType?: boolean },
): { group: FeedQuerySuggestionGroup; context: FeedQueryEditContext } {
  const includeType = options?.includeType ?? false;

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
  const rawValue = colon === -1 ? "" : bare.slice(colon + 1);
  const valueNegated = /^not:/i.test(rawValue);
  const activeValue = rawValue.replace(/^not:/i, "");
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
              const first = (member.first_name ?? "").toLowerCase();
              const unique =
                first !== "" &&
                members.filter(
                  (m) => (m.first_name ?? "").toLowerCase() === first,
                ).length === 1;
              return {
                insert: unique ? first : member.email,
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
      case "status": {
        const items: FeedQuerySuggestion[] = [];
        for (const status of TASK_RUN_STATUSES) {
          if (!startsWith(status)) continue;
          items.push({
            insert: status,
            label: status,
            icon: statusDot(status),
          });
        }
        return { heading: "Run status", items };
      }
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

  return { group, context: { chunk, activeKey, typed, valueNegated } };
}
