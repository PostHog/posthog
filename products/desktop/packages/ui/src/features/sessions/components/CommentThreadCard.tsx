import {
  ArrowBendUpLeftIcon,
  ArrowCounterClockwiseIcon,
  ArrowSquareOutIcon,
  CaretRightIcon,
  CheckCircleIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import {
  Avatar,
  AvatarFallback,
  AvatarImage,
  Button,
  cn,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";
import type { UserBasic } from "@posthog/shared/domain-types";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { MentionText } from "@posthog/ui/features/canvas/components/MentionText";
import type { CommentEntry } from "@posthog/ui/features/canvas/components/taskCommentThreads";
import { githubCommentComponents } from "@posthog/ui/features/editor/components/githubCommentImages";
import { githubRehypePlugins } from "@posthog/ui/features/editor/components/githubMarkdownPlugins";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { KeyHint } from "@posthog/ui/primitives/KeyHint";
import { toast } from "@posthog/ui/primitives/toast";
import { cachedImageUrl } from "@posthog/ui/shell/cachedImageUrl";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import {
  type KeyboardEvent,
  type ReactElement,
  type ReactNode,
  useState,
} from "react";
import { CommentComposer } from "./CommentComposer";
import type { HighlightResolution } from "./commentViewTypes";
import { adjacentThread, moveThreadFocus } from "./threadListFocus";

const MAX_REPLIES_SHOWN = 2;
const TEXT_INSET = "pl-8";

function CommentAvatar({
  entry,
  size,
}: {
  entry: CommentEntry;
  size: "xs" | "sm";
}): ReactElement {
  // A PostHog author keeps the avatar and hue they have everywhere else;
  // a GitHub author only ever comes with a url.
  if (entry.user || !entry.avatarUrl) {
    return <UserAvatar user={entry.user} size={size} />;
  }
  return (
    <Avatar size={size}>
      <AvatarImage src={cachedImageUrl(entry.avatarUrl)} alt="" />
      <AvatarFallback>{entry.authorName.slice(0, 2)}</AvatarFallback>
    </Avatar>
  );
}

function CommentBody({
  entry,
  reply = false,
  actions,
}: {
  entry: CommentEntry;
  reply?: boolean;
  actions?: ReactNode;
}): ReactElement {
  return (
    <div className={reply ? "mt-2.5" : undefined}>
      <div className="flex min-h-6 items-center gap-2">
        <span className="flex w-6 shrink-0 justify-center">
          <CommentAvatar entry={entry} size={reply ? "xs" : "sm"} />
        </span>
        <span className="truncate font-medium text-xs">{entry.authorName}</span>
        <span className="shrink-0 text-muted-foreground text-xs">
          {formatRelativeTimeShort(entry.createdAt)}
        </span>
        {actions}
      </div>
      {entry.format === "markdown" ? (
        <div
          className={`${TEXT_INSET} break-words text-[13px] leading-relaxed [&_img]:max-w-full [&_p]:m-0 [&_pre]:max-w-full [&_pre]:overflow-x-auto`}
        >
          <MarkdownRenderer
            content={entry.body}
            rehypePlugins={githubRehypePlugins}
            componentsOverride={githubCommentComponents}
          />
        </div>
      ) : (
        <MentionText
          content={entry.body}
          className={`${TEXT_INSET} block whitespace-pre-wrap break-words text-[13px] leading-relaxed`}
        />
      )}
    </div>
  );
}

function ThreadAction({
  label,
  shortcut,
  disabled,
  onClick,
  children,
}: {
  label: string;
  shortcut: string;
  disabled?: boolean;
  onClick: () => void;
  children: ReactNode;
}): ReactElement {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            size="icon-sm"
            aria-label={label}
            disabled={disabled}
            onClick={onClick}
          >
            {children}
          </Button>
        }
      />
      <TooltipContent side="top" className="flex items-center gap-1.5">
        {label}
        <KeyHint>{shortcut}</KeyHint>
      </TooltipContent>
    </Tooltip>
  );
}

/**
 * One thread, with its replies and the reply/resolve controls. Selecting it is
 * the caller's business: in a list spanning several resources that means
 * opening the resource and locating the anchor.
 */
export function CommentThreadCard({
  threadId,
  entries,
  selected,
  pulsing,
  resolved,
  members,
  resolution,
  busy,
  source,
  canReply = true,
  canResolve = true,
  viewHref,
  onSelect,
  onReply,
  onResolve,
}: {
  threadId: string;
  /** Root first, then replies. */
  entries: CommentEntry[];
  selected: boolean;
  pulsing: boolean;
  resolved: boolean;
  members: UserBasic[];
  resolution?: HighlightResolution;
  busy: boolean;
  /** Names the resource the thread lives on, for cross-resource lists. */
  source?: ReactNode;
  /** GitHub conversation comments take neither replies nor resolution. */
  canReply?: boolean;
  canResolve?: boolean;
  /** Where to read/act on a thread that can't be handled in place. */
  viewHref?: string | null;
  onSelect: () => void;
  onReply: (content: string, mentions: number[]) => void | Promise<void>;
  onResolve: (resolved: boolean) => void | Promise<void>;
}) {
  const [replying, setReplying] = useState(false);
  const [reply, setReply] = useState("");
  const [showAllReplies, setShowAllReplies] = useState(false);
  const [root, ...replies] = entries;
  if (!root) return null;

  const hiddenReplies =
    showAllReplies || replies.length <= MAX_REPLIES_SHOWN
      ? 0
      : replies.length - 1;
  const shownReplies = replies.slice(hiddenReplies);

  const setThreadResolved = (next: boolean) => {
    Promise.resolve(onResolve(next))
      .then(() => {
        toast.success(next ? "Thread resolved" : "Thread reopened", {
          id: `comment-thread-state-${threadId}`,
          action: {
            label: "Undo",
            onClick: () => {
              Promise.resolve(onResolve(!next)).catch(() => undefined);
            },
          },
        });
      })
      .catch(() => undefined);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    moveThreadFocus(event);
    if (event.key === "r" && canReply) {
      event.preventDefault();
      setReplying(true);
    } else if (event.key === "e" && canResolve && !busy) {
      event.preventDefault();
      const current = event.currentTarget;
      const next = adjacentThread(current);
      setThreadResolved(!resolved);
      requestAnimationFrame(() => {
        if (!current.isConnected) next?.focus();
      });
    }
  };

  const actions = (canReply || canResolve) && (
    <span
      className={cn(
        "pointer-events-auto ml-auto flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-focus-within/thread:opacity-100 group-hover/thread:opacity-100",
        selected && "opacity-100",
      )}
    >
      {canReply && (
        <ThreadAction
          label="Reply"
          shortcut="R"
          onClick={() => setReplying(true)}
        >
          <ArrowBendUpLeftIcon />
        </ThreadAction>
      )}
      {canResolve && (
        <ThreadAction
          label={resolved ? "Reopen" : "Resolve"}
          shortcut="E"
          disabled={busy}
          onClick={() => setThreadResolved(!resolved)}
        >
          {resolved ? <ArrowCounterClockwiseIcon /> : <CheckCircleIcon />}
        </ThreadAction>
      )}
    </span>
  );

  return (
    <div
      className={cn(
        "group/thread relative border-border/70 border-b px-3 pt-2 pb-3 transition-colors duration-300",
        selected
          ? "bg-fill-selected before:absolute before:inset-y-0 before:left-0 before:w-0.5 before:bg-primary"
          : "hover:bg-fill-hover",
        // Inset, so a pane that clips its overflow can't shave the highlight.
        pulsing && "ring-2 ring-primary ring-inset",
        resolved && "opacity-70",
      )}
      data-comment-thread-id={threadId}
    >
      <Button
        type="button"
        variant="outline"
        className="absolute inset-0 h-auto w-full scroll-mt-8 rounded-none opacity-0 focus-visible:opacity-100"
        aria-label="Open comment thread"
        data-thread-focus="thread"
        onClick={onSelect}
        onKeyDown={onKeyDown}
      />
      <div className="pointer-events-none relative [&_a]:pointer-events-auto [&_button]:pointer-events-auto">
        {source && <div className={`${TEXT_INSET} mb-1 min-w-0`}>{source}</div>}
        {resolution === "orphaned" && (
          <div
            className={`${TEXT_INSET} mb-1 flex items-center gap-1 text-amber-700 text-xs dark:text-amber-300`}
          >
            <WarningCircleIcon />
            The highlighted text changed
          </div>
        )}
        <CommentBody entry={root} actions={actions} />
        {hiddenReplies > 0 && (
          <div className={TEXT_INSET}>
            <Button
              size="xs"
              variant="link-muted"
              className="mt-1.5 px-0"
              onClick={() => setShowAllReplies(true)}
            >
              <CaretRightIcon />
              Show {hiddenReplies} earlier{" "}
              {hiddenReplies === 1 ? "reply" : "replies"}
            </Button>
          </div>
        )}
        {shownReplies.map((entry) => (
          <CommentBody key={entry.id} entry={entry} reply />
        ))}
      </div>
      {/* A conversation comment can only be read here and acted on in GitHub;
          dead Reply/Resolve buttons would just discard whatever was typed, so
          it gets a link out instead. */}
      {!canReply && !canResolve && viewHref ? (
        <div className={`relative ${TEXT_INSET} mt-1.5`}>
          <Button
            size="xs"
            variant="link-muted"
            className="px-0"
            onClick={() => openExternalUrl(viewHref)}
          >
            View on GitHub
            <ArrowSquareOutIcon />
          </Button>
        </div>
      ) : replying ? (
        <div className={`relative ${TEXT_INSET} mt-2.5`}>
          <CommentComposer
            value={reply}
            onValueChange={setReply}
            onSubmit={async (content, mentions) => {
              await onReply(content, mentions);
              setReply("");
              setReplying(false);
              setShowAllReplies(true);
            }}
            onCancel={() => setReplying(false)}
            members={members}
            placeholder={
              members.length > 0 ? "Reply… Type @ to mention someone" : "Reply…"
            }
            rows={1}
            disabled={busy}
            submitLabel="Reply"
            autoFocus
          />
        </div>
      ) : (
        selected &&
        canReply && (
          <div className={`relative ${TEXT_INSET} mt-2.5`}>
            <Button
              variant="outline"
              size="lg"
              className="w-full cursor-text justify-start"
              onClick={() => setReplying(true)}
            >
              Reply…
            </Button>
          </div>
        )
      )}
    </div>
  );
}
