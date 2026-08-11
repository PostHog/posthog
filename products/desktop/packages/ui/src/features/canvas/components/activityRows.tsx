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
  ariaLabel,
}: {
  gutter: ReactNode;
  children: ReactNode;
  timestamp: string;
  /** Shown when the row is opened. Absent means there is nothing more to say. */
  detail?: ReactNode;
  defaultOpen?: boolean;
  ariaLabel?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const hasDetail = detail !== undefined && detail !== null;
  const header = (
    <div className="flex min-w-0 items-baseline gap-1.5 text-[13px] leading-5">
      <span className="min-w-0 truncate">{children}</span>
      <ThreadTimestamp dateTime={timestamp} />
      {hasDetail && (
        <CaretRightIcon
          size={11}
          aria-hidden
          className={cn(
            "ml-auto shrink-0 self-center text-muted-foreground opacity-0 transition-all group-hover:opacity-100",
            open && "rotate-90 opacity-100",
          )}
        />
      )}
    </div>
  );
  return (
    <div
      className={cn(
        "group flex items-start gap-2 rounded-md py-2 pr-2 pl-2 transition-colors",
        hasDetail &&
          "cursor-pointer focus-within:bg-gray-3 hover:bg-gray-3 has-[:focus-visible]:bg-gray-3",
      )}
    >
      <div className="flex w-10 shrink-0 justify-center">{gutter}</div>
      <div className="min-w-0 flex-1 pt-0.5">
        {hasDetail ? (
          <>
            <button
              type="button"
              aria-expanded={open}
              aria-label={ariaLabel}
              className="w-full text-left focus-visible:outline-none"
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

function IconBubble({ children }: { children: ReactNode }) {
  return (
    <span className="relative z-10 flex size-6 items-center justify-center rounded-full bg-gray-3 ring-4 ring-gray-1">
      {children}
    </span>
  );
}

const EVENT_ICONS: Record<ActivityEvent["kind"], ReactNode> = {
  run_started: <PlayIcon size={12} weight="fill" className="text-blue-11" />,
  run_failed: <XCircleIcon size={14} weight="fill" className="text-red-11" />,
  awaiting_input: (
    <WarningIcon size={13} weight="fill" className="text-amber-11" />
  ),
  artifact_created: <FileTextIcon size={13} className="text-violet-11" />,
  artifact_revised: (
    <ArrowsClockwiseIcon size={12} className="text-violet-11" />
  ),
  canvas_created: <FileTextIcon size={13} className="text-violet-11" />,
  pr_created: <GitPullRequestIcon size={13} className="text-gray-12" />,
  pr_merged: <GitPullRequestIcon size={13} className="text-violet-11" />,
  pr_closed: <GitPullRequestIcon size={13} className="text-red-11" />,
  message_forwarded: <ArrowRightIcon size={12} className="text-blue-11" />,
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
    case "pr_created":
    case "pr_merged":
    case "pr_closed":
      return <DetailBlock>{event.payload.prUrl}</DetailBlock>;
    default:
      return null;
  }
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
}: {
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
      gutter={<IconBubble>{EVENT_ICONS[event.kind]}</IconBubble>}
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
}: {
  status: string;
  timestamp: string;
}) {
  const succeeded = status === "completed";
  return (
    <TimelineRow
      gutter={
        <IconBubble>
          {succeeded ? (
            <CheckCircleIcon
              size={14}
              weight="fill"
              className="text-green-11"
            />
          ) : (
            <XCircleIcon size={14} weight="fill" className="text-red-11" />
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
}: {
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
      gutter={
        // Decorative: the author's name is written beside it.
        <div
          aria-hidden
          className="relative z-10 rounded-full ring-4 ring-gray-1"
        >
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
              {thread.content}
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
            <Button variant="default" size="sm" onClick={onSelect}>
              Open thread
            </Button>
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
}: {
  thread: TaskCommentThreadSummary;
  state: string;
}) {
  const author = thread.state_event?.author ?? null;
  const resolved = state === "resolved";
  return (
    <TimelineRow
      gutter={
        <IconBubble>
          {resolved ? (
            <CheckCircleIcon
              size={14}
              weight="fill"
              className="text-green-11"
            />
          ) : (
            <WarningCircleIcon
              size={14}
              weight="fill"
              className="text-amber-11"
            />
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
    // role=status so a screen reader hears the wait; a bare div can't carry the label.
    <div
      className="relative px-1 py-2"
      role="status"
      aria-label="Loading timeline"
    >
      <div
        aria-hidden
        className="pointer-events-none absolute top-6 bottom-6 left-8 w-px bg-border"
      />
      <div className="relative z-10">
        {/* Widths vary so the block reads as copy rather than a progress bar. */}
        {[36, 52, 44, 60, 40].map((width, index) => (
          <div
            // biome-ignore lint/suspicious/noArrayIndexKey: fixed-length decorative placeholder
            key={index}
            className="flex items-start gap-2 py-2 pr-2 pl-2"
          >
            <div className="flex w-10 shrink-0 justify-center">
              <Skeleton className="size-6 rounded-full ring-4 ring-gray-1" />
            </div>
            <div className="min-w-0 flex-1 pt-1">
              <Skeleton
                className="h-3 rounded"
                style={{ width: `${width}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
