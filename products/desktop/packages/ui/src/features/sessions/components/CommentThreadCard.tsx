import {
  ArrowCounterClockwise,
  ArrowSquareOutIcon,
  ChatCircle,
  CheckCircle,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  Avatar,
  AvatarFallback,
  AvatarImage,
  Button,
  Card,
  CardContent,
  Separator,
} from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";
import type { UserBasic } from "@posthog/shared/domain-types";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { MentionText } from "@posthog/ui/features/canvas/components/MentionText";
import type { CommentEntry } from "@posthog/ui/features/canvas/components/taskCommentThreads";
import { githubCommentComponents } from "@posthog/ui/features/editor/components/githubCommentImages";
import { githubRehypePlugins } from "@posthog/ui/features/editor/components/githubMarkdownPlugins";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { type ReactNode, useState } from "react";
import { CommentComposer } from "./CommentComposer";
import type { HighlightResolution } from "./commentViewTypes";

function CommentBody({ entry }: { entry: CommentEntry }) {
  return (
    <div className="flex gap-2 py-2">
      {/* A PostHog author keeps the avatar and hue they have everywhere else;
          a GitHub author only ever comes with a url. */}
      {entry.user || !entry.avatarUrl ? (
        <UserAvatar user={entry.user} size="sm" />
      ) : (
        <Avatar size="sm">
          <AvatarImage src={entry.avatarUrl} alt="" />
          <AvatarFallback>{entry.authorName.slice(0, 2)}</AvatarFallback>
        </Avatar>
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="truncate font-medium text-xs">
            {entry.authorName}
          </span>
          <span className="shrink-0 text-muted-foreground text-xs">
            {formatRelativeTimeShort(entry.createdAt)}
          </span>
        </div>
        {entry.format === "markdown" ? (
          <div className="mt-1 break-words text-[13px] leading-relaxed [&_img]:max-w-full [&_p]:m-0 [&_pre]:max-w-full [&_pre]:overflow-x-auto">
            <MarkdownRenderer
              content={entry.body}
              rehypePlugins={githubRehypePlugins}
              componentsOverride={githubCommentComponents}
            />
          </div>
        ) : (
          <MentionText
            content={entry.body}
            className="mt-1 block whitespace-pre-wrap break-words text-[13px] leading-relaxed"
          />
        )}
      </div>
    </div>
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
  const [root, ...replies] = entries;
  if (!root) return null;

  return (
    <Card
      className={`gap-0 p-0 transition-all duration-300 ${
        selected ? "border-accent bg-accent/5" : ""
      } ${
        // Inset, so a pane that clips its overflow can't shave the highlight.
        pulsing ? "ring-2 ring-accent ring-inset" : ""
      } ${resolved ? "opacity-70" : ""}`}
      data-comment-thread-id={threadId}
    >
      <CardContent className="relative p-3">
        <Button
          type="button"
          variant="outline"
          className="absolute inset-0 h-auto w-full opacity-0"
          aria-label="Open comment thread"
          onClick={onSelect}
        />
        <div className="pointer-events-none relative [&_a]:pointer-events-auto [&_button]:pointer-events-auto">
          <div className="w-full text-left">
            {source}
            {resolution === "orphaned" && (
              <div className="mb-1.5 flex items-center gap-1 text-amber-700 text-xs dark:text-amber-300">
                <WarningCircle />
                The highlighted text changed
              </div>
            )}
            <CommentBody entry={root} />
          </div>
        </div>
        {/* Replies sit at the root's indentation: a thread this narrow reads as
            one conversation, and nesting only stole width from the text. */}
        <div className="pointer-events-none relative">
          {replies.map((entry) => (
            <CommentBody key={entry.id} entry={entry} />
          ))}
        </div>
        {/* A conversation comment can only be read here and acted on in GitHub;
            dead Reply/Resolve buttons would just discard whatever was typed, so
            it gets a link out instead. */}
        {(canReply || canResolve || viewHref) && <Separator className="my-2" />}
        {!canReply && !canResolve && viewHref ? (
          <div className="relative">
            <Button
              size="sm"
              variant="outline"
              onClick={() => openExternalUrl(viewHref)}
            >
              <ArrowSquareOutIcon />
              View on GitHub
            </Button>
          </div>
        ) : replying ? (
          <CommentComposer
            value={reply}
            onValueChange={setReply}
            onSubmit={async (content, mentions) => {
              await onReply(content, mentions);
              setReply("");
              setReplying(false);
            }}
            onCancel={() => setReplying(false)}
            members={members}
            placeholder={
              members.length > 0 ? "Reply… Type @ to mention someone" : "Reply…"
            }
            rows={2}
            disabled={busy}
            submitLabel="Reply"
            autoFocus
          />
        ) : (
          (canReply || canResolve) && (
            <div className="relative flex gap-1">
              {canReply && (
                <Button size="sm" onClick={() => setReplying(true)}>
                  <ChatCircle />
                  Reply
                </Button>
              )}
              {canResolve && (
                <Button
                  size="sm"
                  disabled={busy}
                  onClick={() => {
                    Promise.resolve(onResolve(!resolved)).catch(
                      () => undefined,
                    );
                  }}
                >
                  {resolved ? <ArrowCounterClockwise /> : <CheckCircle />}
                  {resolved ? "Reopen" : "Resolve"}
                </Button>
              )}
            </div>
          )
        )}
      </CardContent>
    </Card>
  );
}
