/**
 * Adding an event kind means an entry in `EVENT_TONES` and `EVENT_ICONS` plus a line of copy.
 */

import {
  ArrowCounterClockwiseIcon,
  ArrowsClockwiseIcon,
  CaretRightIcon,
  ChatCircleIcon,
  CheckIcon,
  FileTextIcon,
  GitCommitIcon,
  GitMergeIcon,
  GitPullRequestIcon,
  PaperPlaneTiltIcon,
  PlayIcon,
  PlusIcon,
  ProhibitIcon,
  QuestionIcon,
  SquaresFourIcon,
  UserSwitchIcon,
  XIcon,
} from "@phosphor-icons/react";
import type { CommentScope } from "@posthog/api-client/posthog-client";
import {
  type ActivityEvent,
  type ArtifactPayload,
  type CommentEventPayload,
  type CommitsPushedPayload,
  type PrPayload,
  prLabel,
} from "@posthog/core/canvas/activityEvents";
import type { GroupableActivityEvent } from "@posthog/core/canvas/activityGrouping";
import type { ChangedFile } from "@posthog/core/git/router-schemas";
import { xmlToContent } from "@posthog/core/message-editor/content";
import {
  Button,
  ChatBubble,
  ChatBubbleContent,
  cn,
  Skeleton,
} from "@posthog/quill";
import { splitMentionSegments } from "@posthog/shared";
import type {
  TaskCommentThreadSummary,
  UserBasic,
} from "@posthog/shared/domain-types";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { MentionText } from "@posthog/ui/features/canvas/components/MentionText";
import { ThreadTimestamp } from "@posthog/ui/features/canvas/components/ThreadTimestamp";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { useCommitChangedFiles } from "@posthog/ui/features/git-interaction/useGitQueries";
import { ChatMarkdown } from "@posthog/ui/features/sessions/components/chat-thread/ChatMarkdown";
import { useCommentsQuery } from "@posthog/ui/features/sessions/components/useComments";
import { useArtifactDownload } from "@posthog/ui/features/sessions/useArtifactDownload";
import { ArtifactChip } from "@posthog/ui/primitives/ArtifactChip";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { getObjectKind } from "@posthog/ui/utils/objectKinds";
import { parseHttpsUrl } from "@posthog/ui/utils/posthogLinks";
import { type ReactNode, useMemo, useState } from "react";

export function TimelineRow({
  gutter,
  children,
  timestamp,
  detail,
  defaultOpen = false,
  connectedAbove = true,
  connectedBelow = true,
  onShowInChat,
  ariaLabel,
}: {
  gutter: ReactNode;
  children: ReactNode;
  timestamp: string;
  detail?: ReactNode;
  /** Only a prompt row carries one, because a prompt is the same conversation item in both
   *  panes and so resolves exactly. Absent when no transcript is mounted to answer. */
  onShowInChat?: () => void;
  defaultOpen?: boolean;
  connectedAbove?: boolean;
  connectedBelow?: boolean;
  ariaLabel?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  // The jump counts as detail, so a row whose only content is the action still opens.
  const body =
    detail !== undefined && detail !== null ? (
      <div className="space-y-1.5">
        {detail}
        {onShowInChat && (
          <DetailAction onClick={onShowInChat}>Show in chat</DetailAction>
        )}
      </div>
    ) : onShowInChat ? (
      <DetailAction onClick={onShowInChat}>Show in chat</DetailAction>
    ) : null;
  const hasDetail = body !== null;
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
        "group flex items-stretch gap-2 rounded-md py-2.5 pr-2 pl-2 transition-colors",
        hasDetail &&
          "cursor-pointer focus-within:bg-gray-2 hover:bg-gray-2 has-[:focus-visible]:bg-gray-2",
      )}
    >
      {/* The connector lives inside the row, so the hover fill paints behind it and
          consecutive rows' segments meet into one line. Two halves, so the first and last
          rows stop at their own bead. The offsets are the row's py-2.5: this column
          stretches only to the content box, so each segment has to cross the padding to
          reach the next row's. 11px is the bead's centre. */}
      <div className="relative flex w-10 shrink-0 justify-center self-stretch">
        {connectedAbove && (
          <span
            aria-hidden
            className="-translate-x-1/2 -top-2.5 absolute left-1/2 h-[21px] w-px bg-gray-6"
          />
        )}
        {connectedBelow && (
          <span
            aria-hidden
            className="-translate-x-1/2 -bottom-2.5 absolute top-[11px] left-1/2 w-px bg-gray-6"
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
                line-height as a strut, which pushes the copy 3px below the bead. */}
            <button
              type="button"
              aria-expanded={open}
              aria-label={ariaLabel}
              className="flex w-full text-left focus-visible:outline-none"
              onClick={() => setOpen((current) => !current)}
            >
              {header}
            </button>
            {open && <div className="mt-1.5">{body}</div>}
          </>
        ) : (
          header
        )}
      </div>
    </div>
  );
}

/**
 * Two recipes because the sizes need different contrast. A bead uses the soft steps, which
 * stay quiet beside the copy. A badge is 12px, too small to read as a wash, so it uses solid
 * step 9 with the foreground that scale is designed for: dark on amber, light on the rest.
 */
const BEAD_TONES = {
  neutral: "border-gray-6 bg-gray-3 text-gray-11",
  blue: "border-blue-6 bg-blue-3 text-blue-11",
  green: "border-green-6 bg-green-3 text-green-11",
  amber: "border-amber-6 bg-amber-3 text-amber-11",
  violet: "border-violet-6 bg-violet-3 text-violet-11",
  red: "border-red-6 bg-red-3 text-red-11",
} as const;

const BADGE_TONES = {
  neutral: "bg-gray-10 text-gray-1",
  blue: "bg-blue-9 text-white",
  green: "bg-green-9 text-white",
  amber: "bg-amber-9 text-amber-12",
  violet: "bg-violet-9 text-white",
  red: "bg-red-9 text-white",
} as const;

type BeadTone = keyof typeof BEAD_TONES;

/** Opaque and above the connector, so the line reads as running into it. */
export function EventBead({
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

export function PersonBead({
  user,
  badge,
  badgeTone = "neutral",
}: {
  user?: UserBasic | null;
  badge: ReactNode;
  badgeTone?: BeadTone;
}) {
  return (
    // Decorative: the name and the action are written beside it, so keep the initials out
    // of the row's accessible name.
    <span aria-hidden className="relative z-10 block size-5">
      {/* quill's avatar is a rounded square; every bead in the gutter is a circle. */}
      <UserAvatar user={user} size="xs" className="size-5 rounded-full" />
      <span
        className={cn(
          "-right-1 -bottom-1 absolute flex size-3 items-center justify-center rounded-full ring-2 ring-background",
          BADGE_TONES[badgeTone],
        )}
      >
        {badge}
      </span>
    </span>
  );
}

export const MESSAGE_BADGE = <PaperPlaneTiltIcon size={8} weight="fill" />;
export const COMMENT_BADGE = <ChatCircleIcon size={8} weight="fill" />;
export const CREATED_BADGE = <PlusIcon size={8} weight="bold" />;

const EVENT_TONES: Record<ActivityEvent["kind"], BeadTone> = {
  run_started: "blue",
  run_failed: "red",
  commits_pushed: "neutral",
  awaiting_input: "amber",
  artifact_created: "violet",
  artifact_revised: "violet",
  canvas_created: "violet",
  // Comment rows draw the commenter's avatar bead instead; kept for the map's completeness.
  comment_added: "neutral",
  comment_state_changed: "green",
  pr_created: "neutral",
  pr_merged: "violet",
  pr_closed: "red",
  message_forwarded: "neutral",
  task_handed_off: "blue",
};

/** No glyph here is itself a circle: a ring inside a ring reads as a mistake at this size,
 *  so a failure is a bare ✕ and a success a bare ✓. */
const EVENT_ICONS: Record<ActivityEvent["kind"], ReactNode> = {
  run_started: <PlayIcon size={9} weight="fill" />,
  run_failed: <XIcon size={10} weight="bold" />,
  commits_pushed: <GitCommitIcon size={11} />,
  awaiting_input: <QuestionIcon size={11} weight="bold" />,
  artifact_created: <FileTextIcon size={11} />,
  artifact_revised: <ArrowsClockwiseIcon size={11} />,
  canvas_created: <SquaresFourIcon size={11} />,
  comment_added: <ChatCircleIcon size={11} />,
  comment_state_changed: <CheckIcon size={11} weight="bold" />,
  pr_created: <GitPullRequestIcon size={11} />,
  pr_merged: <GitMergeIcon size={11} />,
  pr_closed: <ProhibitIcon size={11} />,
  message_forwarded: <PaperPlaneTiltIcon size={9} weight="fill" />,
  task_handed_off: <UserSwitchIcon size={11} />,
};

function eventLabel(
  event: ActivityEvent,
  runCount: number,
  runOrdinal: number,
): ReactNode {
  switch (event.kind) {
    case "run_started":
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
          Agent{" "}
          {event.payload.referenceType === "posthog_object"
            ? "added"
            : "created"}{" "}
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
    case "comment_added":
      return "Comment added";
    case "comment_state_changed":
      return event.payload.state === "resolved"
        ? "Comment thread resolved"
        : "Comment thread reopened";
    case "message_forwarded":
      return "Message sent to the agent";
    case "task_handed_off": {
      const { fromDisplayName, toDisplayName } = event.payload;
      return (
        <>
          {fromDisplayName
            ? `${fromDisplayName} handed the task off to `
            : "Task handed off to "}
          <span className="font-medium">{toDisplayName}</span>
        </>
      );
    }
  }
}

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
      const { commits, total, repository } = event.payload;
      return (
        <DetailBlock>
          <div className="max-h-56 space-y-1.5 overflow-y-auto overscroll-contain">
            {commits.map((commit) => (
              <PushedCommitRow
                key={commit.sha}
                commit={commit}
                repository={repository}
              />
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

/**
 * Mention tokens and the composer's XML chips are not markdown, and a markdown parser mangles
 * them (`@[Name](email)` becomes a mailto link), so a message carrying either goes through
 * `MentionText` instead.
 */
export function MessageBody({ content }: { content: string }) {
  const hasOwnMarkup = useMemo(() => {
    const { segments } = xmlToContent(content);
    return (
      segments.some((segment) => segment.type === "chip") ||
      segments.some(
        (segment) =>
          segment.type !== "chip" &&
          splitMentionSegments(segment.text).some(
            (part) => part.type === "mention",
          ),
      )
    );
  }, [content]);
  return (
    // The chat's markdown is sized for the transcript's column, so pull its paragraphs,
    // list items and code back down to the size of the row copy.
    <div className="whitespace-pre-wrap break-words text-[12.5px] [&_code]:text-[11px]! [&_li]:text-[12.5px]! [&_p]:text-[12.5px]! [&_p]:leading-[1.55]!">
      {hasOwnMarkup ? (
        <MentionText content={content} />
      ) : (
        <ChatMarkdown content={content} />
      )}
    </div>
  );
}

export function MessageBubble({ content }: { content: string }) {
  return (
    <ChatBubble variant="default">
      {/* The bubble's own `whitespace-pre-wrap` would double markdown's block spacing. */}
      <ChatBubbleContent className="whitespace-normal">
        <MessageBody content={content} />
      </ChatBubbleContent>
    </ChatBubble>
  );
}

/**
 * The same surface an artifact chip wears in the transcript
 * (`ArtifactChip`), so a file named in a message and a file named in the
 * activity feed read as one thing. Only the padding differs: this is block
 * copy, not a run of inline text.
 */
export function DetailBlock({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "break-words rounded-md border border-border bg-muted px-2.5 py-1.5 text-[12.5px]",
        className,
      )}
    >
      {children}
    </div>
  );
}

/**
 * The same chip a message names a file with, so the file reads the same on a
 * row as it does mid-sentence. Openable and downloadable only where the task's
 * own view is mounted to open it in.
 */
export function ArtifactEventDetail({
  payload,
  taskId,
  onOpen,
}: {
  payload: ArtifactPayload;
  /** The task to fetch the file from, set only where the row can act at all. */
  taskId?: string;
  onOpen?: () => void;
}) {
  const { download, downloadingId } = useArtifactDownload();
  const runId = payload.runId;
  const isPostHogReference = payload.referenceType === "posthog_object";
  const objectKind = getObjectKind(payload.objectKind ?? "");
  const canDownload = Boolean(
    !isPostHogReference && taskId && runId && payload.artifactId,
  );

  return (
    <ArtifactChip
      label={payload.name}
      name={payload.name}
      meta={
        isPostHogReference
          ? `${objectKind.kindLabel} · ${objectKind.source}`
          : `v${payload.version}`
      }
      onOpen={onOpen}
      onDownload={
        canDownload && taskId && runId
          ? () => {
              void download({
                taskId,
                runId,
                artifactId: payload.artifactId,
                name: payload.name,
              });
            }
          : undefined
      }
      downloading={downloadingId === payload.artifactId}
    />
  );
}

function CommitSha({ sha, url }: { sha: string; url: string | null }) {
  const short = sha.slice(0, 7);
  // url comes from caller-controlled run output, so a bare https check would
  // let a crafted payload open any host behind a github-looking label. Pin it
  // to github.com, the same gate usePrArtifact applies to run-output PR links.
  const parsed = url ? parseHttpsUrl(url) : null;
  const safeUrl = parsed?.origin === "https://github.com" ? parsed.href : null;
  if (!safeUrl) {
    return (
      <span className="shrink-0 font-mono text-[11.5px] text-muted-foreground">
        {short}
      </span>
    );
  }
  return (
    <button
      type="button"
      onClick={() => openExternalUrl(safeUrl)}
      className="shrink-0 cursor-pointer font-mono text-[11.5px] text-muted-foreground hover:text-foreground hover:underline"
      aria-label={`Open commit ${short} on GitHub`}
    >
      {short}
    </button>
  );
}

/** The payload is identity-only; TimelineRow defers this detail to the first expand,
 *  so the GitHub file fetch runs then. Without gh access the identity line stands alone. */
function PushedCommitRow({
  commit,
  repository,
}: {
  commit: CommitsPushedPayload["commits"][number];
  repository: string | null;
}) {
  const { data: files, isLoading } = useCommitChangedFiles(
    repository,
    commit.sha,
  );
  return (
    <div className="min-w-0">
      <div className="flex min-w-0 items-baseline gap-2">
        <CommitSha sha={commit.sha} url={commit.url} />
        <span className="min-w-0 truncate">{commit.subject}</span>
      </div>
      {isLoading ? (
        <CommitFilesSkeleton />
      ) : (
        files && files.length > 0 && <CommitFilesList files={files} />
      )}
    </div>
  );
}

const FILE_STATUS_GLYPHS: Record<
  ChangedFile["status"],
  { letter: string; tone: string }
> = {
  added: { letter: "A", tone: "text-green-11" },
  modified: { letter: "M", tone: "text-muted-foreground" },
  deleted: { letter: "D", tone: "text-red-11" },
  renamed: { letter: "R", tone: "text-amber-11" },
  // Not a state GitHub's commit API produces; covered for the shared ChangedFile type.
  untracked: { letter: "A", tone: "text-green-11" },
};

/** Mirrors CommitFileRow's geometry (letter, path, stats) so the loaded list lands without a jump. */
function CommitFilesSkeleton() {
  return (
    <div className="mt-0.5 space-y-px">
      {["w-3/5", "w-2/5", "w-1/2"].map((width) => (
        <div key={width} className="flex h-[17px] items-center gap-1.5">
          <Skeleton className="size-2.5 shrink-0 rounded-[3px]" />
          <Skeleton className={cn("h-2.5", width)} />
          <Skeleton className="ml-auto h-2.5 w-8 shrink-0" />
        </div>
      ))}
    </div>
  );
}

export function CommitFilesList({ files }: { files: ChangedFile[] }) {
  return (
    <div className="mt-0.5 space-y-px">
      {files.map((file) => (
        <CommitFileRow key={file.path} file={file} />
      ))}
    </div>
  );
}

function CommitFileRow({ file }: { file: ChangedFile }) {
  const glyph = FILE_STATUS_GLYPHS[file.status];
  const split = file.path.lastIndexOf("/");
  // The directory truncates first so the file name stays readable on long paths.
  const dir = split === -1 ? "" : file.path.slice(0, split + 1);
  const base = split === -1 ? file.path : file.path.slice(split + 1);
  const title = file.originalPath
    ? `${file.originalPath} → ${file.path}`
    : file.path;
  return (
    <div
      className="flex min-w-0 items-baseline gap-1.5 font-mono text-[11px] leading-[17px]"
      title={title}
    >
      <span
        className={cn("w-3 shrink-0 text-center font-semibold", glyph.tone)}
      >
        {glyph.letter}
      </span>
      <span className="flex min-w-0 flex-1 items-baseline">
        {dir && (
          <span className="min-w-0 truncate text-muted-foreground">{dir}</span>
        )}
        <span
          className={cn(
            "shrink-0",
            file.status === "deleted" && "text-muted-foreground line-through",
          )}
        >
          {base}
        </span>
      </span>
      {((file.linesAdded ?? 0) > 0 || (file.linesRemoved ?? 0) > 0) && (
        <span className="shrink-0 text-[10.5px] tabular-nums">
          {(file.linesAdded ?? 0) > 0 && (
            <span className="text-green-11">+{file.linesAdded}</span>
          )}{" "}
          {(file.linesRemoved ?? 0) > 0 && (
            <span className="text-red-11">-{file.linesRemoved}</span>
          )}
        </span>
      )}
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
  /** A single-run task doesn't say "run 1". */
  runCount: number;
  /** Which run this row starts, counted over the feed rather than stamped by the backend. */
  runOrdinal?: number;
  detail?: ReactNode;
}) {
  const ObjectIcon =
    event.kind === "artifact_created" &&
    event.payload.referenceType === "posthog_object"
      ? getObjectKind(event.payload.objectKind ?? "").icon
      : null;
  return (
    <TimelineRow
      connectedAbove={connectedAbove}
      connectedBelow={connectedBelow}
      gutter={
        <EventBead tone={EVENT_TONES[event.kind]}>
          {ObjectIcon ? <ObjectIcon size={11} /> : EVENT_ICONS[event.kind]}
        </EventBead>
      }
      timestamp={timestamp}
      detail={detail ?? eventDetail(event)}
    >
      {eventLabel(event, runCount, runOrdinal)}
    </TimelineRow>
  );
}

function PrGroupLink({ payload }: { payload: PrPayload }) {
  const label = prLabel(payload);
  // Same gate CommitSha applies: the url comes from run output, so a crafted
  // payload must not turn a github-looking label into a link anywhere else.
  const parsed = parseHttpsUrl(payload.prUrl);
  const safeUrl = parsed?.origin === "https://github.com" ? parsed.href : null;
  if (!safeUrl) {
    return <div className="truncate text-muted-foreground">{label}</div>;
  }
  return (
    <button
      type="button"
      onClick={() => openExternalUrl(safeUrl)}
      className="block max-w-full cursor-pointer truncate text-left hover:underline"
    >
      {label}
    </button>
  );
}

/**
 * One row for a stretch of events that each said the same thing. The count is the news; the
 * events themselves are the detail, so nothing the individual rows carried is lost.
 */
export function GroupedEventRow({
  events,
  timestamp,
  connectedAbove = true,
  connectedBelow = true,
}: {
  events: GroupableActivityEvent[];
  timestamp: string;
  connectedAbove?: boolean;
  connectedBelow?: boolean;
}) {
  const first = events[0];
  if (!first) return null;

  if (first.kind === "commits_pushed") {
    const pushes = events.flatMap((event) =>
      event.kind === "commits_pushed" ? [event.payload] : [],
    );
    const total = pushes.reduce((sum, push) => sum + push.total, 0);
    const listed = pushes.reduce((sum, push) => sum + push.commits.length, 0);
    const branch = first.payload.branch;
    return (
      <TimelineRow
        connectedAbove={connectedAbove}
        connectedBelow={connectedBelow}
        gutter={
          <EventBead tone={EVENT_TONES.commits_pushed}>
            {EVENT_ICONS.commits_pushed}
          </EventBead>
        }
        timestamp={timestamp}
        detail={
          <DetailBlock>
            <div className="max-h-56 space-y-1.5 overflow-y-auto overscroll-contain">
              {pushes.flatMap((push) =>
                push.commits.map((commit) => (
                  <PushedCommitRow
                    key={commit.sha}
                    commit={commit}
                    repository={push.repository}
                  />
                )),
              )}
              {total > listed && (
                <div className="text-muted-foreground">
                  and {total - listed} more
                </div>
              )}
            </div>
          </DetailBlock>
        }
      >
        {`${total} commits pushed`}
        {branch && <span className="text-muted-foreground"> to {branch}</span>}
      </TimelineRow>
    );
  }

  const verb =
    first.kind === "pr_created"
      ? "opened"
      : first.kind === "pr_merged"
        ? "merged"
        : "closed";
  const pulls = events.flatMap((event) =>
    event.kind === "commits_pushed" ? [] : [event.payload],
  );
  return (
    <TimelineRow
      connectedAbove={connectedAbove}
      connectedBelow={connectedBelow}
      gutter={
        <EventBead tone={EVENT_TONES[first.kind]}>
          {EVENT_ICONS[first.kind]}
        </EventBead>
      }
      timestamp={timestamp}
      detail={
        <DetailBlock>
          <div className="max-h-56 space-y-1 overflow-y-auto overscroll-contain">
            {pulls.map((payload) => (
              <PrGroupLink key={payload.prUrl} payload={payload} />
            ))}
          </div>
        </DetailBlock>
      }
    >
      {`${pulls.length} pull requests ${verb}`}
    </TimelineRow>
  );
}

/** The ending of a run that predates the event rows, derived from the task. */
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
        <EventBead tone={succeeded ? "green" : "red"}>
          {succeeded ? (
            <CheckIcon size={11} weight="bold" />
          ) : (
            <XIcon size={10} weight="bold" />
          )}
        </EventBead>
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
        <PersonBead
          user={author}
          badge={COMMENT_BADGE}
          badgeTone={isMentioned ? "amber" : "neutral"}
        />
      }
      timestamp={thread.last_activity_at}
      detail={
        <div className="space-y-1.5">
          {/* A comment stays a quote rather than a chat bubble: it points at the text it
              was left on, which is quoted above it. */}
          <DetailBlock>
            {thread.selected_text && (
              <div className="mb-1 truncate text-muted-foreground italic">
                “{thread.selected_text}”
              </div>
            )}
            <MessageBody content={thread.content} />
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
        <PersonBead
          user={author}
          badge={
            resolved ? (
              <CheckIcon size={8} weight="bold" />
            ) : (
              <ArrowCounterClockwiseIcon size={8} weight="bold" />
            )
          }
          badgeTone={resolved ? "green" : "amber"}
        />
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

export function CommentEventRow({
  event,
  author,
  timestamp,
  taskId,
  onOpenThread,
  connectedAbove = true,
  connectedBelow = true,
}: {
  event: Extract<
    ActivityEvent,
    { kind: "comment_added" | "comment_state_changed" }
  >;
  author: UserBasic | null;
  timestamp: string;
  taskId: string;
  onOpenThread?: () => void;
  connectedAbove?: boolean;
  connectedBelow?: boolean;
}) {
  const name = author ? userDisplayName(author) : "Someone";
  const target = event.payload.targetName;
  if (event.kind === "comment_state_changed") {
    const resolved = event.payload.state === "resolved";
    return (
      <TimelineRow
        connectedAbove={connectedAbove}
        connectedBelow={connectedBelow}
        gutter={
          <PersonBead
            user={author}
            badge={
              resolved ? (
                <CheckIcon size={8} weight="bold" />
              ) : (
                <ArrowCounterClockwiseIcon size={8} weight="bold" />
              )
            }
            badgeTone={resolved ? "green" : "amber"}
          />
        }
        timestamp={timestamp}
      >
        <span className="font-medium">{name}</span>{" "}
        <span className="text-muted-foreground">
          {resolved ? "resolved a thread" : "reopened a thread"}
          {target ? " on" : ""}
        </span>
        {target && (
          <>
            {" "}
            <span className="font-medium">{target}</span>
          </>
        )}
      </TimelineRow>
    );
  }
  return (
    <TimelineRow
      connectedAbove={connectedAbove}
      connectedBelow={connectedBelow}
      gutter={<PersonBead user={author} badge={COMMENT_BADGE} />}
      timestamp={timestamp}
      detail={
        <CommentEventDetail
          taskId={taskId}
          payload={event.payload}
          onOpenThread={onOpenThread}
        />
      }
    >
      <span className="font-medium">{name}</span>{" "}
      <span className="text-muted-foreground">
        commented{target ? " on" : ""}
      </span>
      {target && (
        <>
          {" "}
          <span className="font-medium">{target}</span>
        </>
      )}
    </TimelineRow>
  );
}

const COMMENT_EVENT_SCOPES: readonly string[] = [
  "task",
  "task_artifact",
  "desktop_canvas",
];

function CommentEventDetail({
  taskId,
  payload,
  onOpenThread,
}: {
  taskId: string;
  payload: CommentEventPayload;
  onOpenThread?: () => void;
}) {
  const target =
    COMMENT_EVENT_SCOPES.includes(payload.scope) && payload.itemId
      ? { scope: payload.scope as CommentScope, itemId: payload.itemId }
      : null;
  const { data, isLoading } = useCommentsQuery(target, taskId, {
    live: false,
  });
  const comments = data ?? [];
  const root = comments.find((c) => c.id === payload.rootCommentId);
  const replyCount = comments.filter(
    (c) => c.source_comment === payload.rootCommentId,
  ).length;
  const context = root?.item_context as { anchor?: { quote?: unknown } } | null;
  const quote =
    typeof context?.anchor?.quote === "string" ? context.anchor.quote : null;
  return (
    <div className="space-y-1.5">
      {isLoading ? (
        <DetailBlock>
          <Skeleton className="h-3 w-3/5" />
        </DetailBlock>
      ) : root ? (
        <DetailBlock>
          {quote && (
            <div className="mb-1 truncate text-muted-foreground italic">
              “{quote}”
            </div>
          )}
          <MessageBody content={root.content ?? ""} />
        </DetailBlock>
      ) : null}
      {replyCount > 0 && (
        <div className="truncate text-[12.5px] text-muted-foreground">
          {replyCount} {replyCount === 1 ? "reply" : "replies"}
        </div>
      )}
      {onOpenThread && (
        <DetailAction onClick={onOpenThread}>Open thread</DetailAction>
      )}
    </div>
  );
}

/** Shown once, on the panel's first draw. It never returns, because a loader over rows
 *  already on screen reads as the content disappearing. */
export function ActivityLoadingState() {
  return (
    <output className="relative block px-1 py-2" aria-label="Loading timeline">
      <div>
        {/* Widths vary so the block reads as copy rather than a progress bar. */}
        {[36, 52, 44, 60, 40].map((width) => (
          <div key={width} className="flex items-start gap-2 py-2.5 pr-2 pl-2">
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
      gutter={<PersonBead user={author} badge={MESSAGE_BADGE} />}
      timestamp={timestamp}
      detail={<MessageBubble content={content} />}
    >
      <span className="font-medium">{userDisplayName(author)}</span>{" "}
      <span className="text-muted-foreground">
        <MentionText content={firstLine} />
      </span>
    </TimelineRow>
  );
}
