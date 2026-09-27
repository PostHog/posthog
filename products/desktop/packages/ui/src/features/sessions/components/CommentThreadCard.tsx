import {
  ArrowBendUpLeftIcon,
  ArrowCounterClockwiseIcon,
  ArrowSquareOutIcon,
  CaretRightIcon,
  CheckCircleIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import { avatarColor } from "@posthog/core/auth/avatarColor";
import {
  Avatar,
  AvatarFallback,
  AvatarImage,
  Button,
  cn,
  Kbd,
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
import { toast } from "@posthog/ui/primitives/toast";
import { cachedImageUrl } from "@posthog/ui/shell/cachedImageUrl";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import {
  type KeyboardEvent,
  type ReactElement,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from "react";
import { CommentComposer } from "./CommentComposer";
import type { HighlightResolution } from "./commentViewTypes";
import { adjacentThread, moveThreadFocus } from "./threadListFocus";

const MAX_REPLIES_SHOWN = 2;
const TEXT_INSET = "pl-7";

function CommentAvatar({ entry }: { entry: CommentEntry }): ReactElement {
  // A PostHog author keeps the avatar and hue they have everywhere else;
  // a GitHub author only ever comes with a url.
  if (entry.user) {
    return <UserAvatar user={entry.user} size="xs" />;
  }
  const color = avatarColor(entry.authorName);
  return (
    <Avatar size="xs">
      {entry.avatarUrl && (
        <AvatarImage src={cachedImageUrl(entry.avatarUrl)} alt="" />
      )}
      <AvatarFallback style={{ backgroundColor: color.bg, color: color.text }}>
        {entry.authorName.slice(0, 2).toUpperCase()}
      </AvatarFallback>
    </Avatar>
  );
}

function CommentBody({
  entry,
  actions,
}: {
  entry: CommentEntry;
  actions?: ReactNode;
}): ReactElement {
  return (
    <div>
      <div className="flex min-h-6 items-center gap-2">
        <CommentAvatar entry={entry} />
        <span className="truncate font-medium text-[13px]">
          {entry.authorName}
        </span>
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
        <Kbd>{shortcut}</Kbd>
      </TooltipContent>
    </Tooltip>
  );
}

export function CommentQuote({
  quote,
  version,
}: {
  quote?: string | null;
  version?: string | null;
}): ReactElement | null {
  if (!quote && !version) return null;
  return (
    <span
      className={cn(
        "flex min-w-0 items-center gap-1.5 text-muted-foreground text-xs",
        quote && "border-[rgb(250_204_21)] border-l-2 pl-2",
      )}
      title={quote ?? undefined}
    >
      {version && <span className="shrink-0">{version} ·</span>}
      {quote && <span className="min-w-0 truncate">{quote}</span>}
    </span>
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
  const openButtonRef = useRef<HTMLButtonElement>(null);
  const focusAfterRemoval = useRef<HTMLElement | null>(null);
  useEffect(
    () => () => {
      const next = focusAfterRemoval.current;
      if (next?.isConnected && document.activeElement === document.body) {
        next.focus();
      }
    },
    [],
  );
  const [reply, setReply] = useState("");
  const [showAllReplies, setShowAllReplies] = useState(false);
  const [root, ...replies] = entries;
  if (!root) return null;

  const hiddenReplies =
    showAllReplies || replies.length <= MAX_REPLIES_SHOWN
      ? 0
      : replies.length - 1;
  const shownReplies = replies.slice(hiddenReplies);
  const startReply = () => setReplying(true);
  const stopReply = () => {
    setReplying(false);
    setReply("");
  };

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
      .catch(() => {
        focusAfterRemoval.current = null;
      });
  };

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    moveThreadFocus(event);
    if (event.key === "r" && canReply) {
      event.preventDefault();
      startReply();
    } else if (event.key === "e" && canResolve && !busy) {
      event.preventDefault();
      focusAfterRemoval.current = adjacentThread(event.currentTarget);
      setThreadResolved(!resolved);
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
        <ThreadAction label="Reply" shortcut="R" onClick={startReply}>
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
        "group/thread relative border-border/70 border-b p-3 transition-colors duration-300 has-[>[data-thread-focus]:focus-visible]:ring-2 has-[>[data-thread-focus]:focus-visible]:ring-ring/50 has-[>[data-thread-focus]:focus-visible]:ring-inset",
        selected ? "bg-fill-selected" : "hover:bg-fill-hover",
        // Inset, so a pane that clips its overflow can't shave the highlight.
        pulsing && "ring-2 ring-primary ring-inset",
      )}
      data-comment-thread-id={threadId}
    >
      <Button
        type="button"
        variant="outline"
        className="absolute inset-0 h-auto w-full scroll-mt-8 rounded-none opacity-0"
        ref={openButtonRef}
        aria-label="Open comment thread"
        data-thread-focus="thread"
        onClick={onSelect}
        onKeyDown={onKeyDown}
      />
      <div className="pointer-events-none relative [&_a]:pointer-events-auto [&_button]:pointer-events-auto">
        {source && <div className="mb-2 min-w-0">{source}</div>}
        {resolution === "orphaned" && (
          <div className="mb-2 flex items-center gap-1 text-warning-foreground text-xs">
            <WarningCircleIcon />
            The highlighted text changed
          </div>
        )}
        <div className="flex flex-col gap-3">
          <CommentBody entry={root} actions={actions} />
          {hiddenReplies > 0 && (
            <div className={TEXT_INSET}>
              <Button
                size="xs"
                variant="link-muted"
                className="-mt-2 -mb-1 h-5 self-start px-0"
                onClick={() => {
                  setShowAllReplies(true);
                  openButtonRef.current?.focus();
                }}
              >
                <CaretRightIcon />
                Show {hiddenReplies} earlier{" "}
                {hiddenReplies === 1 ? "reply" : "replies"}
              </Button>
            </div>
          )}
          {shownReplies.map((entry) => (
            <CommentBody key={entry.id} entry={entry} />
          ))}
        </div>
      </div>
      {/* A conversation comment can only be read here and acted on in GitHub;
          dead Reply/Resolve buttons would just discard whatever was typed, so
          it gets a link out instead. */}
      {!canReply && !canResolve && viewHref ? (
        <div className={`relative ${TEXT_INSET} mt-2`}>
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
      ) : (
        canReply &&
        (replying || selected || reply) && (
          <div className={`relative ${TEXT_INSET} mt-3`}>
            <CommentComposer
              key={replying ? "replying" : "idle"}
              value={reply}
              onValueChange={setReply}
              onSubmit={async (content, mentions) => {
                await onReply(content, mentions);
                stopReply();
                setShowAllReplies(true);
              }}
              onCancel={
                replying || reply
                  ? () => {
                      stopReply();
                      openButtonRef.current?.focus();
                    }
                  : undefined
              }
              members={members}
              placeholder="Reply…"
              rows={1}
              disabled={busy}
              submitLabel="Reply"
              autoFocus={replying}
              compact
            />
          </div>
        )
      )}
    </div>
  );
}
