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
import { cn } from "@posthog/quill";
import type {
  TaskCommentThreadSummary,
  UserBasic,
} from "@posthog/shared/domain-types";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { ThreadTimestamp } from "@posthog/ui/features/canvas/components/ThreadTimestamp";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import type { ReactNode } from "react";

/** A gutter node, a line of copy and a timestamp, at the same size as every other row's
 *  copy: only the icon distinguishes a lifecycle row from its neighbours. */
export function TimelineRow({
  gutter,
  children,
  timestamp,
  onSelect,
  ariaLabel,
}: {
  gutter: ReactNode;
  children: ReactNode;
  timestamp: string;
  onSelect?: () => void;
  ariaLabel?: string;
}) {
  const activation = onSelect
    ? {
        role: "button" as const,
        tabIndex: 0,
        "aria-label": ariaLabel,
        onClick: onSelect,
        onKeyDown: (event: React.KeyboardEvent<HTMLDivElement>) => {
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          onSelect();
        },
      }
    : {};
  return (
    <div
      className={cn(
        "flex items-start gap-2 py-1.5 pr-2 pl-2",
        onSelect && "cursor-pointer",
      )}
      {...activation}
    >
      <div className="flex w-10 shrink-0 justify-center">{gutter}</div>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-1 text-[13px]">
          <span className="min-w-0 truncate">{children}</span>
          <ThreadTimestamp dateTime={timestamp} />
        </div>
      </div>
    </div>
  );
}

function IconBubble({ children }: { children: ReactNode }) {
  return (
    <span className="relative z-10 flex size-6 items-center justify-center rounded-full bg-gray-3">
      {children}
    </span>
  );
}

const EVENT_ICONS: Record<ActivityEvent["kind"], ReactNode> = {
  run_started: <PlayIcon size={12} weight="fill" className="text-blue-9" />,
  run_failed: <XCircleIcon size={14} weight="fill" className="text-red-9" />,
  awaiting_input: (
    <WarningIcon size={13} weight="fill" className="text-warning" />
  ),
  artifact_created: <FileTextIcon size={13} className="text-violet-9" />,
  artifact_revised: <ArrowsClockwiseIcon size={12} className="text-violet-9" />,
  canvas_created: <FileTextIcon size={13} className="text-violet-9" />,
  pr_created: <GitPullRequestIcon size={13} className="text-gray-11" />,
  pr_merged: <GitPullRequestIcon size={13} className="text-violet-9" />,
  pr_closed: <GitPullRequestIcon size={13} className="text-red-9" />,
  message_forwarded: <ArrowRightIcon size={12} className="text-blue-9" />,
};

/** The sentence an event reads as. Written so a person skimming the panel learns what
 *  happened without opening anything. */
function eventLabel(
  event: ActivityEvent,
  runCount: number,
  runOrdinal: number,
): ReactNode {
  switch (event.kind) {
    case "run_started": {
      const details = [
        event.payload.environment,
        event.payload.branch || null,
      ].filter(Boolean);
      return (
        <>
          {/* A run number only helps once a task has run more than once. */}
          {runCount > 1
            ? `Agent started run ${runOrdinal}`
            : "Agent started work"}
          {details.length > 0 && (
            <span className="text-muted-foreground">
              {" "}
              · {details.join(" · ")}
            </span>
          )}
        </>
      );
    }
    case "run_failed":
      return event.payload.errorSummary ? (
        <>
          Run failed
          <span className="text-muted-foreground">
            {" "}
            · {event.payload.errorSummary}
          </span>
        </>
      ) : (
        "Run failed"
      );
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

export function ActivityEventRow({
  event,
  timestamp,
  runCount,
  runOrdinal = 1,
  onSelect,
}: {
  event: ActivityEvent;
  timestamp: string;
  /** How many runs the task has, so a single-run task doesn't say "run 1". */
  runCount: number;
  /** Which run this row starts, counted over the feed rather than stamped by the backend. */
  runOrdinal?: number;
  onSelect?: () => void;
}) {
  return (
    <TimelineRow
      gutter={<IconBubble>{EVENT_ICONS[event.kind]}</IconBubble>}
      timestamp={timestamp}
      onSelect={onSelect}
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
            <CheckCircleIcon size={14} weight="fill" className="text-green-9" />
          ) : (
            <XCircleIcon size={14} weight="fill" className="text-red-9" />
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
 * One comment thread. The anchor's quoted selection travels with the row, because a
 * comment without the text it points at is just a notification.
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
    <div
      className={cn(
        "flex items-start gap-2 py-1.5 pr-2 pl-2",
        onSelect && "cursor-pointer",
      )}
      {...(onSelect
        ? {
            role: "button" as const,
            tabIndex: 0,
            onClick: onSelect,
            onKeyDown: (event: React.KeyboardEvent<HTMLDivElement>) => {
              if (event.key !== "Enter" && event.key !== " ") return;
              event.preventDefault();
              onSelect();
            },
          }
        : {})}
    >
      <div className="flex w-10 shrink-0 justify-center">
        {/* Decorative: the author's name is written beside it. */}
        <div aria-hidden>
          <UserAvatar user={author} size="sm" className="sticky top-2" />
        </div>
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-1 text-[13px]">
          <span className="min-w-0 truncate">
            <span className="font-medium">{name}</span>{" "}
            <span className="text-muted-foreground">{verb}</span>{" "}
            <span className="font-medium">{thread.target.name}</span>
          </span>
          <ThreadTimestamp dateTime={thread.last_activity_at} />
        </div>
        <div className="mt-1 border-border border-l-2 pl-2">
          {thread.selected_text && (
            <div className="truncate text-[12.5px] text-muted-foreground italic">
              “{thread.selected_text}”
            </div>
          )}
          <div className="line-clamp-2 whitespace-pre-wrap break-words text-[12.5px]">
            {thread.content}
          </div>
        </div>
        {thread.reply_count > 0 && (
          <div className="mt-1 truncate text-[12.5px] text-muted-foreground">
            {thread.reply_count}{" "}
            {thread.reply_count === 1 ? "reply" : "replies"}
            {thread.participants.length > 0 &&
              ` · ${participantNames(thread.participants)}`}
          </div>
        )}
      </div>
    </div>
  );
}

/** Resolve and reopen: state changes with an author and a time, so they read as their own
 *  rows rather than a property of the thread above. */
export function CommentStateRow({
  thread,
  state,
  onSelect,
}: {
  thread: TaskCommentThreadSummary;
  state: string;
  onSelect?: () => void;
}) {
  const author = thread.state_event?.author ?? null;
  const resolved = state === "resolved";
  return (
    <TimelineRow
      gutter={
        <IconBubble>
          {resolved ? (
            <CheckCircleIcon size={14} weight="fill" className="text-green-9" />
          ) : (
            <WarningCircleIcon
              size={14}
              weight="fill"
              className="text-warning"
            />
          )}
        </IconBubble>
      }
      timestamp={thread.state_event?.created_at ?? thread.last_activity_at}
      onSelect={onSelect}
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
