/**
 * The rows the activity timeline draws for one server-emitted event, and for one comment
 * thread.
 *
 * Split out of `ActivityTimeline` so that component stays the merge plus the rail, and a
 * new event is an entry in `EVENT_ICONS` plus a line of copy here.
 */

import {
  ArrowRightIcon,
  ArrowsClockwiseIcon,
  CaretRightIcon,
  CheckCircleIcon,
  FileTextIcon,
  GitCommitIcon,
  GitPullRequestIcon,
  PlayIcon,
  WarningCircleIcon,
  WarningIcon,
  XCircleIcon,
} from "@phosphor-icons/react";
import {
  type ActivityEvent,
  prLabel,
} from "@posthog/core/canvas/activityEvents";
import { Button, cn, Skeleton } from "@posthog/quill";
import type {
  TaskCommentThreadSummary,
  UserBasic,
} from "@posthog/shared/domain-types";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { MentionText } from "@posthog/ui/features/canvas/components/MentionText";
import { ThreadTimestamp } from "@posthog/ui/features/canvas/components/ThreadTimestamp";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { type ReactNode, useState } from "react";

/** One row: a gutter node, a line of copy, a timestamp, and optionally a detail block the
 *  row hides until it is opened.
 *
 *  Collapsed by default so the panel reads as a timeline rather than a wall of content.
 *  A row with no detail is inert — no chevron, no hover target, nothing to click. */
export function TimelineRow({
  gutter,
  children,
  timestamp,
  detail,
  defaultOpen = false,
  connectedAbove = true,
  connectedBelow = true,
  ariaLabel,
}: {
  gutter: ReactNode;
  children: ReactNode;
  timestamp: string;
  /** Shown when the row is opened. Absent means there is nothing more to say. */
  detail?: ReactNode;
  defaultOpen?: boolean;
  /** Draw the line down to the next row. False on the last row, which has nothing to
   *  connect to. */
  connectedAbove?: boolean;
  connectedBelow?: boolean;
  ariaLabel?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const hasDetail = detail !== undefined && detail !== null;
  const header = (
    <div className="flex min-w-0 flex-1 items-center gap-1.5 text-[12.5px] leading-[22px]">
      <span className="min-w-0 truncate">{children}</span>
      <ThreadTimestamp dateTime={timestamp} />
      {hasDetail && (
        <CaretRightIcon
          size={11}
          aria-hidden
          className={cn(
            "ml-auto shrink-0 text-muted-foreground opacity-0 transition-transform group-hover:opacity-60",
            open && "rotate-90 opacity-60",
          )}
        />
      )}
    </div>
  );
  return (
    <div
      className={cn(
        "group flex items-stretch gap-2 rounded-md py-1.5 pr-2 pl-2 transition-colors",
        hasDetail &&
          "cursor-pointer focus-within:bg-gray-2 hover:bg-gray-2 has-[:focus-visible]:bg-gray-2",
      )}
    >
      {/* The connector lives inside the row, so the hover fill paints behind it rather than
          over it, and consecutive rows' segments meet to form one line. It runs through the
          bead's centre; the bead is opaque and sits above it, so the line reads as touching
          it on both sides. The halves are separate so the first and last rows stop at their
          own bead instead of running past it. */}
      <div className="relative flex w-10 shrink-0 justify-center self-stretch">
        {connectedAbove && (
          <span
            aria-hidden
            className="-translate-x-1/2 absolute top-0 left-1/2 h-[11px] w-px bg-gray-8"
          />
        )}
        {connectedBelow && (
          <span
            aria-hidden
            className="-translate-x-1/2 absolute top-[11px] bottom-0 left-1/2 w-px bg-gray-8"
          />
        )}
        {/* h-[22px] is the copy's line height, so the bead centres on the first line
            whatever the row grows to. */}
        <div className="relative z-10 flex h-[22px] items-center">{gutter}</div>
      </div>
      <div className="min-w-0 flex-1">
        {hasDetail ? (
          <>
            {/* flex, not block: an inline-level button contributes its own inherited
                line-height as a strut, which pushed the copy 3px below the bead. */}
            <button
              type="button"
              aria-expanded={open}
              aria-label={ariaLabel}
              className="flex w-full text-left focus-visible:outline-none"
              onClick={() => setOpen((current) => !current)}
            >
              {header}
            </button>
            {open && <div className="mt-1.5">{detail}</div>}
          </>
        ) : (
          header
        )}
      </div>
    </div>
  );
}

/** Each bead is tinted to its event's hue: a wash for the fill, a step up for the edge, and
 *  the high-contrast step for the glyph. Neutral rows keep the gray bead, so colour means
 *  something rather than decorating every row. */
const BEAD_TONES = {
  neutral: "border-gray-7 bg-gray-5 text-gray-12",
  blue: "border-blue-7 bg-blue-4 text-blue-11",
  green: "border-green-7 bg-green-4 text-green-11",
  amber: "border-amber-7 bg-amber-4 text-amber-11",
  violet: "border-violet-7 bg-violet-4 text-violet-11",
  red: "border-red-7 bg-red-4 text-red-11",
} as const;

type BeadTone = keyof typeof BEAD_TONES;

function IconBubble({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: BeadTone;
}) {
  return (
    <span
      className={cn(
        "relative z-10 flex size-5 items-center justify-center rounded-full border",
        BEAD_TONES[tone],
      )}
    >
      {children}
    </span>
  );
}

const EVENT_TONES: Record<ActivityEvent["kind"], BeadTone> = {
  run_started: "blue",
  run_failed: "red",
  commits_pushed: "neutral",
  awaiting_input: "amber",
  artifact_created: "violet",
  artifact_revised: "violet",
  canvas_created: "violet",
  pr_created: "neutral",
  pr_merged: "violet",
  pr_closed: "red",
  message_forwarded: "blue",
};

const EVENT_ICONS: Record<ActivityEvent["kind"], ReactNode> = {
  run_started: <PlayIcon size={10} weight="fill" />,
  run_failed: <XCircleIcon size={12} weight="fill" />,
  commits_pushed: <GitCommitIcon size={11} />,
  awaiting_input: <WarningIcon size={11} weight="fill" />,
  artifact_created: <FileTextIcon size={11} />,
  artifact_revised: <ArrowsClockwiseIcon size={12} />,
  canvas_created: <FileTextIcon size={11} />,
  pr_created: <GitPullRequestIcon size={11} />,
  pr_merged: <GitPullRequestIcon size={11} />,
  pr_closed: <GitPullRequestIcon size={11} />,
  message_forwarded: <ArrowRightIcon size={11} />,
};

/** The sentence an event reads as. Written so a person skimming the panel learns what
 *  happened without opening anything. */
function eventLabel(
  event: ActivityEvent,
  runCount: number,
  runOrdinal: number,
): ReactNode {
  switch (event.kind) {
    case "run_started":
      // A run number only helps once a task has run more than once.
      return runCount > 1
        ? `Agent started run ${runOrdinal}`
        : "Agent started work";
    case "run_failed":
      return "Run failed";
    case "commits_pushed": {
      const { total, branch } = event.payload;
      const count = `${total} commit${total === 1 ? "" : "s"} pushed`;
      return branch ? (
        <>
          {count} <span className="text-muted-foreground">to {branch}</span>
        </>
      ) : (
        count
      );
    }
    case "awaiting_input":
      return "Agent needs input";
    case "artifact_created":
      return (
        <>
          Agent created{" "}
          <span className="font-medium">{event.payload.name}</span>
        </>
      );
    case "artifact_revised":
      return (
        <>
          Agent revised{" "}
          <span className="font-medium">{event.payload.name}</span>
          <span className="text-muted-foreground">
            {" "}
            · v{event.payload.version}
          </span>
        </>
      );
    case "canvas_created":
      return (
        <>
          Agent created{" "}
          <span className="font-medium">{event.payload.name}</span>
        </>
      );
    case "pr_created":
      return (
        <>
          Pull request opened
          <span className="text-muted-foreground">
            {" "}
            · {prLabel(event.payload)}
          </span>
        </>
      );
    case "pr_merged":
    case "pr_closed": {
      const verb = event.kind === "pr_merged" ? "merged" : "closed";
      return (
        <>
          {event.payload.actor
            ? `${event.payload.actor} ${verb} `
            : `Pull request ${verb} `}
          <span className="text-muted-foreground">
            {prLabel(event.payload)}
          </span>
        </>
      );
    }
    case "message_forwarded":
      return "Message sent to the agent";
  }
}

/** What an event has to say beyond its headline, or nothing. */
function eventDetail(event: ActivityEvent): ReactNode {
  switch (event.kind) {
    case "run_failed":
      return event.payload.errorSummary ? (
        <DetailBlock>{event.payload.errorSummary}</DetailBlock>
      ) : null;
    case "run_started": {
      const details = [
        event.payload.environment,
        event.payload.branch || null,
      ].filter(Boolean);
      return details.length > 0 ? (
        <DetailBlock>{details.join(" · ")}</DetailBlock>
      ) : null;
    }
    case "artifact_created":
    case "artifact_revised":
      return (
        <DetailBlock>
          {event.payload.name}
          <span className="text-muted-foreground">
            {" "}
            · v{event.payload.version}
          </span>
        </DetailBlock>
      );
    case "commits_pushed": {
      const { commits, total } = event.payload;
      return (
        <DetailBlock>
          <div className="space-y-1">
            {commits.map((commit) => (
              <div
                key={commit.sha}
                className="flex min-w-0 items-baseline gap-2"
              >
                <span className="shrink-0 font-mono text-[11.5px] text-muted-foreground">
                  {commit.sha.slice(0, 7)}
                </span>
                <span className="min-w-0 truncate">{commit.subject}</span>
              </div>
            ))}
            {total > commits.length && (
              <div className="text-muted-foreground">
                and {total - commits.length} more
              </div>
            )}
          </div>
        </DetailBlock>
      );
    }
    case "pr_created":
    case "pr_merged":
    case "pr_closed":
      return <DetailBlock>{event.payload.prUrl}</DetailBlock>;
    default:
      return null;
  }
}

/** The action under an opened row: a small outline button, so it reads as something to
 *  press rather than as more copy. */
export function DetailAction({
  children,
  onClick,
}: {
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <Button variant="outline" size="xs" onClick={onClick}>
      {children}
    </Button>
  );
}

/** The shared shape of an opened row's content: one quoted block, indented to the copy. */
export function DetailBlock({ children }: { children: ReactNode }) {
  return (
    <div className="break-words rounded-md border-border border-l-2 bg-gray-2 px-2.5 py-1.5 text-[12.5px]">
      {children}
    </div>
  );
}

export function ActivityEventRow({
  event,
  timestamp,
  runCount,
  runOrdinal = 1,
  detail,
  connectedAbove = true,
  connectedBelow = true,
}: {
  connectedAbove?: boolean;
  connectedBelow?: boolean;
  event: ActivityEvent;
  timestamp: string;
  /** How many runs the task has, so a single-run task doesn't say "run 1". */
  runCount: number;
  /** Which run this row starts, counted over the feed rather than stamped by the backend. */
  runOrdinal?: number;
  /** Supplied by the caller for events that carry a card (a canvas, a pull request);
   *  otherwise the row derives its own from the payload. */
  detail?: ReactNode;
}) {
  return (
    <TimelineRow
      connectedAbove={connectedAbove}
      connectedBelow={connectedBelow}
      gutter={
        <IconBubble tone={EVENT_TONES[event.kind]}>
          {EVENT_ICONS[event.kind]}
        </IconBubble>
      }
      timestamp={timestamp}
      detail={detail ?? eventDetail(event)}
    >
      {eventLabel(event, runCount, runOrdinal)}
    </TimelineRow>
  );
}

/** A lifecycle marker derived from the task rather than an event row — the ending of a run
 *  that predates the event rows. */
export function RunStatusRow({
  status,
  timestamp,
  connectedAbove = true,
  connectedBelow = true,
}: {
  status: string;
  timestamp: string;
  connectedAbove?: boolean;
  connectedBelow?: boolean;
}) {
  const succeeded = status === "completed";
  return (
    <TimelineRow
      connectedAbove={connectedAbove}
      connectedBelow={connectedBelow}
      gutter={
        <IconBubble tone={succeeded ? "green" : "red"}>
          {succeeded ? (
            <CheckCircleIcon size={12} weight="fill" />
          ) : (
            <XCircleIcon size={12} weight="fill" />
          )}
        </IconBubble>
      }
      timestamp={timestamp}
    >
      {`Task ${status.replace(/_/g, " ")}`}
    </TimelineRow>
  );
}

function participantNames(participants: UserBasic[]): string {
  return participants.map((person) => userDisplayName(person)).join(", ");
}

/**
 * One comment thread, collapsed to who commented on what. Opening it shows the anchor's
 * quoted selection and the comment itself, because a comment without the text it points at
 * is just a notification — and a button to open the thread where it lives.
 */
export function CommentRow({
  thread,
  isMentioned,
  onSelect,
  connectedAbove = true,
  connectedBelow = true,
}: {
  connectedAbove?: boolean;
  connectedBelow?: boolean;
  thread: TaskCommentThreadSummary;
  /** The current user was mentioned somewhere in the thread. */
  isMentioned: boolean;
  onSelect?: () => void;
}) {
  const author = thread.author ?? null;
  const name = userDisplayName(author);
  const verb = isMentioned ? "mentioned you on" : "commented on";
  return (
    <TimelineRow
      connectedAbove={connectedAbove}
      connectedBelow={connectedBelow}
      gutter={
        // Decorative: the author's name is written beside it.
        <div aria-hidden className="relative z-10 rounded-full">
          <UserAvatar user={author} size="sm" />
        </div>
      }
      timestamp={thread.last_activity_at}
      detail={
        <div className="space-y-1.5">
          <DetailBlock>
            {thread.selected_text && (
              <div className="mb-1 truncate text-muted-foreground italic">
                “{thread.selected_text}”
              </div>
            )}
            <div className="whitespace-pre-wrap break-words">
              <MentionText content={thread.content} />
            </div>
          </DetailBlock>
          {thread.reply_count > 0 && (
            <div className="truncate text-[12.5px] text-muted-foreground">
              {thread.reply_count}{" "}
              {thread.reply_count === 1 ? "reply" : "replies"}
              {thread.participants.length > 0 &&
                ` · ${participantNames(thread.participants)}`}
            </div>
          )}
          {onSelect && (
            <DetailAction onClick={onSelect}>Open thread</DetailAction>
          )}
        </div>
      }
    >
      <span className="font-medium">{name}</span>{" "}
      <span className="text-muted-foreground">{verb}</span>{" "}
      <span className="font-medium">{thread.target.name}</span>
    </TimelineRow>
  );
}

/** Resolve and reopen: state changes with an author and a time, so they read as their own
 *  rows rather than a property of the thread above. */
export function CommentStateRow({
  thread,
  state,
  connectedAbove = true,
  connectedBelow = true,
}: {
  thread: TaskCommentThreadSummary;
  state: string;
  connectedAbove?: boolean;
  connectedBelow?: boolean;
}) {
  const author = thread.state_event?.author ?? null;
  const resolved = state === "resolved";
  return (
    <TimelineRow
      connectedAbove={connectedAbove}
      connectedBelow={connectedBelow}
      gutter={
        <IconBubble tone={resolved ? "green" : "amber"}>
          {resolved ? (
            <CheckCircleIcon size={12} weight="fill" />
          ) : (
            <WarningCircleIcon size={12} weight="fill" />
          )}
        </IconBubble>
      }
      timestamp={thread.state_event?.created_at ?? thread.last_activity_at}
    >
      {author ? (
        <span className="font-medium">{userDisplayName(author)}</span>
      ) : (
        "Someone"
      )}{" "}
      {resolved ? "resolved a thread on" : "reopened a thread on"}{" "}
      <span className="font-medium">{thread.target.name}</span>
    </TimelineRow>
  );
}

/** Shown once, on the panel's first draw: the timeline's own shape rather than a spinner,
 *  so the panel doesn't change size or layout when the rows arrive. It never returns —
 *  a loader over rows already on screen reads as the content disappearing. */
export function ActivityLoadingState() {
  return (
    // <output> is the semantic element for role=status; the label names the wait.
    <output className="relative block px-1 py-2" aria-label="Loading timeline">
      <div>
        {/* Widths vary so the block reads as copy rather than a progress bar. */}
        {[36, 52, 44, 60, 40].map((width) => (
          <div key={width} className="flex items-start gap-2 py-1 pr-2 pl-2">
            <div className="flex w-10 shrink-0 justify-center">
              <Skeleton className="size-5 rounded-full" />
            </div>
            <div className="min-w-0 flex-1 py-1">
              <Skeleton
                className="h-3 rounded"
                style={{ width: `${width}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </output>
  );
}

/** A human reply in the task's thread — the surface comments replaced. Collapsed like
 *  everything else: author and first line on the row, the message when opened. */
export function ThreadReplyRow({
  author,
  content,
  timestamp,
  connectedAbove = true,
  connectedBelow = true,
}: {
  author?: UserBasic | null;
  content: string;
  timestamp: string;
  connectedAbove?: boolean;
  connectedBelow?: boolean;
}) {
  const firstLine = content.trim().split("\n", 1)[0] ?? "";
  return (
    <TimelineRow
      connectedAbove={connectedAbove}
      connectedBelow={connectedBelow}
      gutter={
        <div
          aria-hidden
          className="relative z-10 flex size-5 items-center justify-center overflow-hidden rounded-full border border-gray-7"
        >
          <UserAvatar user={author} size="sm" className="size-5" />
        </div>
      }
      timestamp={timestamp}
      detail={
        <DetailBlock>
          <div className="whitespace-pre-wrap break-words">
            <MentionText content={content} />
          </div>
        </DetailBlock>
      }
    >
      <span className="font-medium">{userDisplayName(author)}</span>{" "}
      <span className="text-muted-foreground">
        <MentionText content={firstLine} />
      </span>
    </TimelineRow>
  );
}
