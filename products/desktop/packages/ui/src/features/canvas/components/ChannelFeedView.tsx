import {
  ArrowSquareOutIcon,
  ChatCircleIcon,
  GitBranchIcon,
  LinkIcon,
  RobotIcon,
} from "@phosphor-icons/react";
import { taskFeedRunStatus } from "@posthog/core/canvas/channelFeed";
import { xmlToPlainText } from "@posthog/core/message-editor/content";
import {
  Avatar,
  AvatarFallback,
  AvatarGroup,
  Badge,
  Card,
  CardContent,
  ChatMarker,
  ChatMarkerContent,
  ChatMessageScroller,
  ChatMessageScrollerButton,
  ChatMessageScrollerContent,
  ChatMessageScrollerItem,
  ChatMessageScrollerProvider,
  ChatMessageScrollerViewport,
  cn,
  Spinner,
  ThreadItem,
  ThreadItemAction,
  ThreadItemActions,
  ThreadItemAuthor,
  ThreadItemBody,
  ThreadItemContent,
  ThreadItemGutter,
  ThreadItemHeader,
  ThreadItemReplies,
  ThreadItemRepliesLabel,
  ThreadItemRepliesMeta,
  ThreadItemTimestamp,
  useChatMessageScroller,
} from "@posthog/quill";
import { formatRelativeTimeShort, getLocalDayDiff } from "@posthog/shared";
import type {
  Task,
  TaskRunStatus,
  UserBasic,
} from "@posthog/shared/domain-types";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { TaskTabIcon } from "@posthog/ui/features/browser-tabs/TaskTabIcon";
import type { ChannelFeedSystemMessage } from "@posthog/ui/features/canvas/hooks/useChannelFeedMessages";
import { useChannelTaskData } from "@posthog/ui/features/canvas/hooks/useChannelTaskData";
import { useTaskThread } from "@posthog/ui/features/canvas/hooks/useTaskThread";
import { taskCardNavigation } from "@posthog/ui/features/canvas/taskCardNavigation";
import { copyChannelLink } from "@posthog/ui/features/canvas/utils/copyChannelLink";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import {
  type SidebarPrState,
  useTaskPrStatus,
} from "@posthog/ui/features/sidebar/useTaskPrStatus";
import { useInView } from "@posthog/ui/primitives/hooks/useInView";
import { Text } from "@radix-ui/themes";
import { Link } from "@tanstack/react-router";
import {
  Fragment,
  memo,
  type ReactNode,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

// Feed rows poll their reply counts slower than the open thread panel — the
// shared query key means an open panel naturally speeds the row up too.
const FEED_REPLIES_POLL_INTERVAL_MS = 15_000;

const STATUS_LABELS: Record<TaskRunStatus, string> = {
  not_started: "Not started",
  queued: "Queued",
  in_progress: "In progress",
  // "Ready", not "Completed": the agent has finished its work and the task is
  // ready to look at, but the change itself isn't necessarily shipped/done.
  completed: "Ready",
  failed: "Failed",
  cancelled: "Cancelled",
};

// Once a PR exists its GitHub state is the truest top-line status — more
// accurate than the run status, which routinely lingers on "in_progress"
// (or a stale cloud status) after the agent opens the PR. Mirrors the PR
// states the sidebar's TaskIcon already renders.
const PR_STATE_LABELS: Record<
  Exclude<SidebarPrState, null>,
  { label: string; variant: "success" | "info" | "default" | "destructive" }
> = {
  merged: { label: "Merged", variant: "default" },
  open: { label: "PR ready", variant: "info" },
  draft: { label: "Draft PR", variant: "default" },
  closed: { label: "Closed", variant: "destructive" },
};

function statusBadge(status: TaskRunStatus) {
  const variant =
    status === "completed"
      ? "success"
      : status === "failed"
        ? "destructive"
        : status === "in_progress"
          ? "info"
          : "default";
  return (
    <Badge variant={variant}>
      {status === "in_progress" && <Spinner className="size-2.5" />}
      {STATUS_LABELS[status]}
    </Badge>
  );
}

// Local calendar-day identity, so tasks created on the same day share a heading
// regardless of time. Uses local getters (not the UTC ISO) so the split lands
// on the viewer's midnight.
function dayKey(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

function ordinal(n: number): string {
  const suffix = ["th", "st", "nd", "rd"];
  const rem = n % 100;
  return `${n}${suffix[(rem - 20) % 10] ?? suffix[rem] ?? suffix[0]}`;
}

// The day-separator label: "Today" / "Yesterday" for the recent days, then a
// weekday + ordinal ("Monday 5th") within the week, adding the month (and the
// year when it differs) further back so older separators stay unambiguous.
function dayLabel(iso: string, now: Date): string {
  const date = new Date(iso);
  const days = getLocalDayDiff(date, now);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  const weekday = date.toLocaleDateString(undefined, { weekday: "long" });
  const day = ordinal(date.getDate());
  if (days < 7) return `${weekday} ${day}`;
  const month = date.toLocaleDateString(undefined, { month: "long" });
  const year =
    date.getFullYear() === now.getFullYear() ? "" : `, ${date.getFullYear()}`;
  return `${weekday}, ${month} ${day}${year}`;
}

interface TaskStatusDisplay {
  // The run/environment badge ("Local", "Completed", "In progress", …).
  base: ReactNode;
  // The PR's GitHub state, shown alongside the run badge when a PR exists.
  prState: Exclude<SidebarPrState, null> | null;
  // Whether the PR has merged — the card lifts this to a purple border + tint.
  isMerged: boolean;
}

// Live status for the card, derived the same way the sidebar's TaskIcon does
// (via useChannelTaskData: local session + workspace + cloud run). The raw
// `latest_run.status` alone is wrong for local runs — the backend row often
// stays "queued" while the agent runs on the creator's machine — so it is
// only trusted for cloud runs and terminal states (which imply a sync).
//
// Once a PR exists its state ("PR ready", "Merged", …) is the sole top-line
// status — it replaces the run badge rather than sitting next to it, so a
// shipped task never reads "Ready + Merged" or a stale "In progress + PR
// ready". A failed/cancelled run suppresses the PR badge instead — that is a
// deliberate end state we should not soften with a PR.
function useTaskStatusDisplay(task: Task): TaskStatusDisplay {
  const data = useChannelTaskData(task);
  const { prState } = useTaskPrStatus({
    id: task.id,
    cloudPrUrl: data?.cloudPrUrl ?? null,
    taskRunEnvironment: data?.taskRunEnvironment ?? null,
  });
  const status = data?.taskRunStatus ?? task.latest_run?.status;
  const environment = data?.taskRunEnvironment ?? task.latest_run?.environment;
  const displayStatus = taskFeedRunStatus({ status, environment });
  // `prState` is resolved async from git/`gh` and is routinely null for cloud
  // tasks (the details fetch hasn't landed, or there's no cached row). But the
  // PR URL itself is a hard signal a PR exists — the card's "PR" link keys off
  // exactly this. Fall back to it so the badge and the link never disagree; a
  // known URL with no resolved state is shown as the neutral "open" ("PR
  // ready"), never something stronger like "merged".
  const hasPrUrl =
    typeof (data?.cloudPrUrl ?? task.latest_run?.output?.pr_url) === "string";
  const effectivePrState: Exclude<SidebarPrState, null> | null =
    prState ?? (hasPrUrl ? "open" : null);
  const showPrState =
    !!effectivePrState && status !== "failed" && status !== "cancelled";

  let base: ReactNode;
  if (data?.needsPermission) {
    // Live, actionable states still win over the PR badge — the agent is
    // waiting on the user right now, which matters more than a PR existing.
    base = <Badge variant="warning">Needs input</Badge>;
  } else if (data?.isGenerating) {
    base = (
      <Badge variant="info">
        <Spinner className="size-2.5" />
        In progress
      </Badge>
    );
  } else if (showPrState) {
    // Otherwise the PR badge is the whole story once a PR exists; skip the run
    // badge so we never show "Ready + Merged" or a stale "In progress".
    base = null;
  } else if (!status) {
    base = <Badge>Draft</Badge>;
  } else if (displayStatus) {
    base = statusBadge(displayStatus);
  } else {
    // Local, non-terminal: the run status is unreliable (the backend row stays
    // "queued" while the agent runs on the creator's machine), so we render no
    // status badge rather than a misleading one.
    base = null;
  }

  return {
    base,
    prState: showPrState ? effectivePrState : null,
    isMerged: showPrState && effectivePrState === "merged",
  };
}

// The merged badge borrows the purple GitHub-merge accent (matching the
// sidebar's TaskIcon merge glyph). Quill has no purple variant, so we tint a
// neutral badge with the Radix purple scale — allowed inline because the
// values are CSS variables, not hardcoded colors.
function PrStateBadge({ prState }: { prState: Exclude<SidebarPrState, null> }) {
  const { label, variant } = PR_STATE_LABELS[prState];
  if (prState === "merged") {
    return (
      <Badge
        variant="default"
        style={{
          backgroundColor: "var(--purple-a3)",
          color: "var(--purple-11)",
        }}
      >
        {label}
      </Badge>
    );
  }
  return <Badge variant={variant}>{label}</Badge>;
}

function TaskStatusBadge({ display }: { display: TaskStatusDisplay }) {
  return (
    <div className="flex shrink-0 items-center gap-1">
      {display.base}
      {display.prState && <PrStateBadge prState={display.prState} />}
    </div>
  );
}

// A kickoff a user just submitted, before its task exists on the backend. The
// feed shows it optimistically so a submit reacts instantly instead of waiting
// on the create round trip; it's swapped for the real card once created.
export interface PendingKickoff {
  id: string;
  prompt: string;
}

// A stable empty default so the `pending` prop doesn't hand memoized children a
// fresh array every render.
const NO_PENDING: PendingKickoff[] = [];

// The task the message kicked off, as a card everyone in the channel sees:
// bold title + status up top, then run metadata.
export function TaskCard({
  task,
  channelId,
  inThread = false,
}: {
  task: Task;
  channelId: string;
  inThread?: boolean;
}) {
  const statusDisplay = useTaskStatusDisplay(task);
  const prUrl =
    typeof task.latest_run?.output?.pr_url === "string"
      ? task.latest_run.output.pr_url
      : undefined;
  const stage = task.latest_run?.stage;
  return (
    <Link
      {...taskCardNavigation(channelId, task.id)}
      preload="intent"
      className={cn(
        "mt-1.5 block w-full text-inherit no-underline outline-none focus-visible:ring-(--accent-8) focus-visible:ring-2",
        inThread ? "rounded-none" : "rounded-sm",
      )}
    >
      <Card
        size="sm"
        className={cn(
          "w-full cursor-pointer py-0 transition-none hover:bg-fill-hover",
          statusDisplay.isMerged
            ? "border-transparent bg-(--purple-a2) shadow-[0_0_0_1px_var(--purple-8)] hover:bg-(--purple-a3) dark:bg-(--purple-a1) dark:hover:bg-(--purple-a2)"
            : "hover:border-border-primary",
          inThread ? "rounded-none" : "rounded-sm",
        )}
      >
        <CardContent className="flex flex-col gap-1 py-2.5">
          <div className="flex items-center justify-between gap-2">
            <div className="flex min-w-0 items-center gap-1.5">
              <TaskTabIcon task={task} size={14} />
              <span className="line-clamp-2 font-medium text-sm">
                {task.title || "Untitled task"}
              </span>
            </div>
            <TaskStatusBadge display={statusDisplay} />
          </div>
          {(stage || task.repository || prUrl) && (
            <div className="flex min-w-0 items-center gap-3">
              {task.repository && (
                <span className="inline-flex items-center gap-1 text-muted-foreground text-xs">
                  <GitBranchIcon size={12} />
                  {task.repository}
                </span>
              )}
              {stage && (
                <Text size="1" className="truncate text-muted-foreground">
                  {stage}
                </Text>
              )}
              {prUrl && (
                <span className="inline-flex shrink-0 items-center gap-1 text-muted-foreground text-xs">
                  <ArrowSquareOutIcon size={12} />
                  PR
                </span>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </Link>
  );
}

// The reply row under the card, always present at a constant height: the
// Slack-style teaser (author facepile, count, last-reply time) once the thread
// has messages, and a quiet "Reply" affordance otherwise. Keeping the row
// mounted at a fixed height means the teaser swaps in after the thread fetch
// lands without shifting the feed — and it surfaces an always-visible way into
// the thread instead of hiding it in the hover toolbar.
//
// The fetch/poll only runs for near-viewport rows (`inView`); off-screen rows
// render the static affordance and idle, so a long feed isn't polling per row.
function ReplyFooter({
  taskId,
  inView,
  onOpenThread,
}: {
  taskId: string;
  inView: boolean;
  onOpenThread: () => void;
}) {
  const { messages } = useTaskThread(taskId, {
    pollIntervalMs: FEED_REPLIES_POLL_INTERVAL_MS,
    enabled: inView,
  });
  const authors = useMemo(() => {
    const seen = new Map<string, (typeof messages)[number]["author"]>();
    for (const message of messages) {
      const key = message.author?.uuid ?? "unknown";
      if (!seen.has(key)) seen.set(key, message.author);
    }
    return [...seen.values()].slice(0, 4);
  }, [messages]);

  if (messages.length === 0) {
    // A single avatar-sized slot keeps this row the exact height of the
    // populated teaser, so swapping to it after the fetch never shifts the feed.
    return (
      <ThreadItemReplies onClick={onOpenThread} className="mt-1">
        <AvatarGroup size="xs">
          <Avatar size="xs">
            <AvatarFallback>
              <ChatCircleIcon size={12} />
            </AvatarFallback>
          </Avatar>
        </AvatarGroup>
        <ThreadItemRepliesLabel>Reply</ThreadItemRepliesLabel>
      </ThreadItemReplies>
    );
  }

  const last = messages[messages.length - 1];
  return (
    <ThreadItemReplies onClick={onOpenThread} className="mt-1">
      <AvatarGroup size="xs">
        {authors.map((author, index) => (
          <UserAvatar key={author?.uuid ?? index} user={author} size="xs" />
        ))}
      </AvatarGroup>
      <ThreadItemRepliesLabel>
        {messages.length} {messages.length === 1 ? "reply" : "replies"}
      </ThreadItemRepliesLabel>
      <ThreadItemRepliesMeta>
        Last reply {formatRelativeTimeShort(last.created_at)}
      </ThreadItemRepliesMeta>
    </ThreadItemReplies>
  );
}

function channelTaskStarter(task: Task): UserBasic | null {
  return task.origin_product === "user_created"
    ? (task.created_by ?? null)
    : null;
}

function ExpandablePrompt({
  children,
  lines,
}: {
  children: string;
  lines: 2 | 4;
}) {
  // The prompt is truncated by hand — not with -webkit-line-clamp — so the
  // "more" toggle can sit inline right after the ellipsis on the last visible
  // line, like "...prompt…more". A hidden copy of the full text is measured to
  // find how much fits, leaving room for the toggle; the visible body renders
  // the cut. Measuring the full text (not the visible, already-cut text) keeps
  // the ResizeObserver stable instead of oscillating as content swaps.
  const observerRef = useRef<ResizeObserver | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [cut, setCut] = useState<string | null>(null);

  const measureRef = useCallback(
    (measure: HTMLDivElement | null) => {
      observerRef.current?.disconnect();
      observerRef.current = null;
      if (!measure || expanded) return;

      const compute = () => {
        const lineHeight = parseFloat(getComputedStyle(measure).lineHeight);
        const maxHeight = lineHeight * lines;
        if (measure.scrollHeight <= maxHeight + 0.5) {
          setCut(null);
          return;
        }
        // Find the longest prefix that still fits in `lines` once "…more" is
        // appended — so the toggle can sit inline right after the ellipsis on the
        // last line. We probe by swapping the measure's text node to "prefix…more"
        // and reading scrollHeight (no per-line geometry), then restore it so the
        // next resize re-measures against the uncut prompt. `children` is the
        // source of truth (and a dep below) so a polled prompt update re-measures
        // even when its rendered size is unchanged.
        const text = measure.firstChild as Text;
        const fits = (end: number) => {
          text.nodeValue = `${children.slice(0, end).trimEnd()}…more`;
          return measure.scrollHeight <= maxHeight + 0.5;
        };
        let lo = 0;
        let hi = children.length;
        let best = 0;
        while (lo <= hi) {
          const mid = (lo + hi) >> 1;
          if (fits(mid)) {
            best = mid;
            lo = mid + 1;
          } else {
            hi = mid - 1;
          }
        }
        text.nodeValue = children;
        // Even when no full character fits alongside "…more" (best === 0, only at
        // extreme narrow widths), still cut so the toggle shows and the prompt
        // stays expandable instead of silently clipped.
        setCut(`${children.slice(0, best).trimEnd()}…`);
      };

      compute();
      const observer = new ResizeObserver(compute);
      observer.observe(measure);
      observerRef.current = observer;
    },
    [children, expanded, lines],
  );

  const truncated = cut !== null;
  const displayText = expanded || !truncated ? children : cut;

  const clampClass = lines === 2 ? "max-h-[2lh]" : "max-h-[4lh]";

  return (
    <ThreadItemBody className="wrap-break-word relative overflow-hidden whitespace-pre-line">
      <div
        aria-hidden
        className="pointer-events-none invisible absolute top-0 right-0 left-0"
      >
        <div ref={measureRef} className="wrap-break-word whitespace-pre-line">
          {children}
        </div>
      </div>
      <div
        className={cn(!expanded && clampClass, !expanded && "overflow-hidden")}
      >
        {displayText}
        {truncated && (
          <button
            type="button"
            aria-expanded={expanded}
            className="pl-1 text-muted-foreground text-xs underline underline-offset-2 hover:text-foreground"
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? "less" : "more"}
          </button>
        )}
      </div>
    </ThreadItemBody>
  );
}

export function TaskFeedRow({
  task,
  actions,
  children,
}: {
  task: Task;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  const starter = channelTaskStarter(task);
  const prompt = useMemo(
    () => xmlToPlainText(task.description ?? "").trim(),
    [task.description],
  );

  return (
    <ThreadItem className="rounded-none py-1 pr-8 hover:bg-fill-hover/50">
      <ThreadItemGutter>
        {starter ? (
          <UserAvatar user={starter} />
        ) : (
          <Avatar>
            <AvatarFallback>
              <RobotIcon size={16} />
            </AvatarFallback>
          </Avatar>
        )}
      </ThreadItemGutter>

      <ThreadItemContent className="min-w-0">
        <ThreadItemHeader>
          <ThreadItemAuthor>
            {starter ? userDisplayName(starter) : "PostHog"}
          </ThreadItemAuthor>
          {!starter && <Badge variant="info">Agent</Badge>}
          <ThreadItemTimestamp
            dateTime={new Date(task.created_at).toISOString()}
          >
            {formatRelativeTimeShort(task.created_at)}
          </ThreadItemTimestamp>
        </ThreadItemHeader>

        <ExpandablePrompt lines={2}>
          {prompt ||
            (starter ? "started a new task" : "A new task was started")}
        </ExpandablePrompt>

        {children}
      </ThreadItemContent>

      {actions}
    </ThreadItem>
  );
}

const FeedItem = memo(function FeedItem({
  task,
  channelId,
  inView,
  onOpenTask,
  onOpenThread,
}: {
  task: Task;
  channelId: string;
  inView: boolean;
  onOpenTask: (task: Task) => void;
  onOpenThread: (task: Task) => void;
}) {
  return (
    <TaskFeedRow
      task={task}
      actions={
        // Replying now lives in the always-visible ReplyFooter, so the hover
        // toolbar only carries per-row actions (copy link, open task). Actions
        // anchor to the row's top-right corner; a top tooltip there overhangs
        // the panel edge and gets clipped by the scroll container, so open
        // tooltips toward the content instead.
        <ThreadItemActions aria-label="Message actions" className="inset-bs-2">
          <ThreadItemAction
            label="Copy link to task"
            onClick={() =>
              void copyChannelLink(channelId, "thread_panel", task.id)
            }
          >
            <LinkIcon size={15} />
          </ThreadItemAction>
          <ThreadItemAction label="Open task" onClick={() => onOpenTask(task)}>
            <ArrowSquareOutIcon size={15} />
          </ThreadItemAction>
        </ThreadItemActions>
      }
    >
      <TaskCard task={task} channelId={channelId} />
      <ReplyFooter
        taskId={task.id}
        inView={inView}
        onOpenThread={() => onOpenThread(task)}
      />
    </TaskFeedRow>
  );
});

// One feed row: owns the scroller item (the `content-visibility` boundary, so
// its box is always laid out and safe to observe) and reports whether it is
// near the viewport, letting `FeedItem` shed off-screen polling.
function FeedRow({
  task,
  channelId,
  onOpenTask,
  onOpenThread,
}: {
  task: Task;
  channelId: string;
  onOpenTask: (task: Task) => void;
  onOpenThread: (task: Task) => void;
}) {
  const [ref, inView] = useInView<HTMLDivElement>({ rootMargin: "1200px 0px" });
  return (
    <ChatMessageScrollerItem
      ref={ref}
      messageId={task.id}
      // Rows already get `content-visibility:auto` from quill, but its default
      // `contain-intrinsic-size` (10rem) under-reserves a feed row (message +
      // task card + replies ≈ 13rem), so off-screen rows collapse too small and
      // the scrollbar jumps as they paint in. A closer estimate keeps scrolling
      // stable; `auto` still remembers each row's real height after first paint.
      className="[contain-intrinsic-size:auto_13rem]"
    >
      <FeedItem
        task={task}
        channelId={channelId}
        inView={inView}
        onOpenTask={onOpenTask}
        onOpenThread={onOpenThread}
      />
    </ChatMessageScrollerItem>
  );
}

// The optimistic kickoff row: the user's message plus a "Starting…" card,
// shown the moment they submit. Deliberately dumb — no per-task data hooks or
// polls (there's no task id to query yet); it's replaced by a real FeedRow as
// soon as the task is created.
function PendingFeedRow({
  pending,
  createdAt,
}: {
  pending: PendingKickoff;
  createdAt: string;
}) {
  return (
    <ChatMessageScrollerItem
      messageId={pending.id}
      className="[contain-intrinsic-size:auto_13rem]"
    >
      <ThreadItem className="rounded-none py-4 pr-8">
        <ThreadItemGutter>
          <Avatar>
            <AvatarFallback>
              <Spinner className="size-4" />
            </AvatarFallback>
          </Avatar>
        </ThreadItemGutter>
        <ThreadItemContent className="min-w-0">
          <ThreadItemHeader>
            <ThreadItemAuthor>You</ThreadItemAuthor>
            <ThreadItemTimestamp dateTime={createdAt}>now</ThreadItemTimestamp>
          </ThreadItemHeader>
          <ExpandablePrompt lines={4}>{pending.prompt}</ExpandablePrompt>
          <Card
            size="sm"
            className="mt-1.5 w-full max-w-[820px] rounded-sm py-0"
          >
            <CardContent className="py-2.5">
              <Badge variant="info">
                <Spinner className="size-2.5" />
                Starting…
              </Badge>
            </CardContent>
          </Card>
        </ThreadItemContent>
      </ThreadItem>
    </ChatMessageScrollerItem>
  );
}

// A card-less feed row for a synthetic announcement. Rows with an `author`
// render as that user (initials avatar + name — e.g. "Adam L · joined mobile");
// the rest render as "PostHog / Agent" (context lifecycle updates). Same chrome
// as a task row, minus the task card and reply footer.
function SystemFeedRow({ message }: { message: ChannelFeedSystemMessage }) {
  return (
    <ChatMessageScrollerItem messageId={message.id}>
      <ThreadItem className="rounded-none py-1 pr-8">
        <ThreadItemGutter>
          {message.author ? (
            <UserAvatar user={message.author} />
          ) : (
            <Avatar>
              <AvatarFallback>
                <RobotIcon size={16} />
              </AvatarFallback>
            </Avatar>
          )}
        </ThreadItemGutter>
        <ThreadItemContent className="min-w-0">
          <ThreadItemHeader>
            <ThreadItemAuthor>
              {message.author ? userDisplayName(message.author) : "PostHog"}
            </ThreadItemAuthor>
            {!message.author && <Badge variant="info">Agent</Badge>}
            <ThreadItemTimestamp dateTime={message.createdAt}>
              {formatRelativeTimeShort(message.createdAt)}
            </ThreadItemTimestamp>
          </ThreadItemHeader>
          <ThreadItemBody className="wrap-break-word text-muted-foreground">
            {message.text}
          </ThreadItemBody>
        </ThreadItemContent>
      </ThreadItem>
    </ChatMessageScrollerItem>
  );
}

// Follow the feed to the bottom when *this* user posts, but not when a
// teammate's card arrives via polling — a new `pending` kickoff is only ever
// added by the local composer, so it's the right signal. Must live inside the
// scroller provider to reach `scrollToEnd`. Renders nothing.
function FollowOwnPost({ latestPendingId }: { latestPendingId?: string }) {
  const { scrollToEnd } = useChatMessageScroller();
  const prevRef = useRef(latestPendingId);
  useEffect(() => {
    if (latestPendingId && latestPendingId !== prevRef.current) {
      scrollToEnd();
    }
    prevRef.current = latestPendingId;
  }, [latestPendingId, scrollToEnd]);
  return null;
}

// A single feed entry, either a real task card or a synthetic system row, tagged
// with the timestamp used to interleave the two.
type FeedEntry =
  | { kind: "task"; id: string; createdAt: string; task: Task }
  | {
      kind: "system";
      id: string;
      createdAt: string;
      message: ChannelFeedSystemMessage;
    };

// The Slack-style channel feed: every task kicked off in the channel, oldest
// first, rendered as a kickoff message + task card. Multiplayer — the list is
// team-visible and polls for teammates' cards and status flips. Synthetic
// "PostHog agent" system rows (context lifecycle) are interleaved by timestamp.
export function ChannelFeedView({
  channelId,
  tasks,
  pending = NO_PENDING,
  systemMessages,
  isLoading,
  emptyState,
  intro,
  onOpenTask,
  onOpenThread,
}: {
  channelId: string;
  tasks: Task[];
  pending?: PendingKickoff[];
  systemMessages?: ChannelFeedSystemMessage[];
  isLoading: boolean;
  emptyState?: React.ReactNode;
  /** Rendered pinned above the first entry — the Slack-style channel intro
   * (name, creation line, onboarding card). When set, the feed renders even
   * with no entries instead of falling back to `emptyState`. */
  intro?: ReactNode;
  onOpenTask: (task: Task) => void;
  onOpenThread: (task: Task) => void;
}) {
  // Merge tasks + system rows into one chronological list. ISO timestamps sort
  // lexically, so a plain string compare is chronological. Announcements are
  // posted 1ms before the task they describe; if the backend truncates that
  // sub-second offset the timestamps tie, so break ties system-row-first to
  // keep the announcement above its card.
  const entries = useMemo<FeedEntry[]>(() => {
    const merged: FeedEntry[] = [
      ...tasks.map((task) => ({
        kind: "task" as const,
        id: task.id,
        createdAt: task.created_at,
        task,
      })),
      ...(systemMessages ?? []).map((message) => ({
        kind: "system" as const,
        id: message.id,
        createdAt: message.createdAt,
        message,
      })),
    ];
    merged.sort(
      (a, b) =>
        a.createdAt.localeCompare(b.createdAt) ||
        (a.kind === b.kind ? 0 : a.kind === "system" ? -1 : 1),
    );
    return merged;
  }, [tasks, systemMessages]);

  const viewportRef = useRef<HTMLDivElement>(null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: channelId is a trigger — switching channels or finishing the initial load swaps/completes the rows without a remount, so re-land at the latest message
  useLayoutEffect(() => {
    if (isLoading) return;
    const viewport = viewportRef.current;
    if (viewport) viewport.scrollTop = viewport.scrollHeight;
  }, [channelId, isLoading]);

  // Wait for the complete feed: the scroller's initial end-scroll fires once,
  // so mounting around partial rows would land it short of the latest message.
  if (isLoading && pending.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner />
      </div>
    );
  }

  if (entries.length === 0 && pending.length === 0 && !intro) {
    return <div className="flex-1 overflow-y-auto">{emptyState}</div>;
  }

  const now = new Date();
  const latestPendingId = pending[pending.length - 1]?.id;

  return (
    <ChatMessageScrollerProvider defaultScrollPosition="end">
      <FollowOwnPost latestPendingId={latestPendingId} />
      <ChatMessageScroller className="min-h-0 flex-1">
        <ChatMessageScrollerViewport ref={viewportRef}>
          {/* Horizontal padding is load-bearing: ThreadItem's actions float at
              the row's top-right corner (absolute, past the row edge). Without a
              gutter they hug the scroll container and get clipped. */}
          <ChatMessageScrollerContent className="mx-auto w-full gap-0 py-4">
            {intro}
            {entries.map((entry, index) => {
              const previous = entries[index - 1];
              const showDayMarker =
                !previous ||
                dayKey(previous.createdAt) !== dayKey(entry.createdAt);
              return (
                <Fragment key={entry.id}>
                  {showDayMarker && (
                    <ChatMarker variant="separator">
                      <ChatMarkerContent>
                        {dayLabel(entry.createdAt, now)}
                      </ChatMarkerContent>
                    </ChatMarker>
                  )}
                  {entry.kind === "task" ? (
                    <FeedRow
                      task={entry.task}
                      channelId={channelId}
                      onOpenTask={onOpenTask}
                      onOpenThread={onOpenThread}
                    />
                  ) : (
                    <SystemFeedRow message={entry.message} />
                  )}
                </Fragment>
              );
            })}
            {pending.map((p) => (
              <PendingFeedRow
                key={p.id}
                pending={p}
                createdAt={now.toISOString()}
              />
            ))}
          </ChatMessageScrollerContent>
        </ChatMessageScrollerViewport>
        <ChatMessageScrollerButton />
      </ChatMessageScroller>
    </ChatMessageScrollerProvider>
  );
}
