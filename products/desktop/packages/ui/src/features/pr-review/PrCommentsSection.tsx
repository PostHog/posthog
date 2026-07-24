import { ArrowSquareOutIcon, ChatCircleIcon } from "@phosphor-icons/react";
import { Spinner } from "@posthog/quill";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { NestedButton } from "@posthog/ui/primitives/NestedButton";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { useMemo, useState } from "react";
import { openExternalUrl } from "../../shell/openExternal";
import { PrSectionHeader } from "./PrSectionHeader";
import { usePrComments } from "./usePrComments";
import { usePrReviewThreads } from "./usePrReviewThreads";

interface CommentItem {
  key: string;
  author: string;
  avatarUrl: string | null;
  body: string;
  createdAt: string;
  url: string | null;
  /** Set for inline review comments; null for conversation comments. */
  filePath: string | null;
  resolved: boolean;
}

interface PrCommentsSectionProps {
  prUrl: string;
}

/**
 * Collapsed-by-default list of everything said on a PR: conversation
 * comments plus inline review comments, in chronological order.
 */
export function PrCommentsSection({ prUrl }: PrCommentsSectionProps) {
  const commentsQuery = usePrComments(prUrl);
  const threadsQuery = usePrReviewThreads(prUrl);
  const [collapsed, setCollapsed] = useState(true);

  const items = useMemo((): CommentItem[] => {
    // Conversation items mix issue comments and review summaries, whose ids
    // come from different GitHub id spaces — key on createdAt too.
    const conversation = (commentsQuery.data ?? []).map(
      (comment): CommentItem => ({
        key: `conv-${comment.id}-${comment.createdAt}`,
        author: comment.author,
        avatarUrl: comment.avatarUrl,
        body: comment.body,
        createdAt: comment.createdAt,
        url: comment.url,
        filePath: null,
        resolved: false,
      }),
    );
    const review = (threadsQuery.data ?? []).flatMap((thread) =>
      thread.comments.map(
        (comment): CommentItem => ({
          key: `review-${comment.id}`,
          author: comment.user.login,
          avatarUrl: comment.user.avatar_url || null,
          body: comment.body,
          createdAt: comment.created_at,
          url: `${prUrl}#discussion_r${comment.id}`,
          filePath: thread.filePath,
          resolved: thread.isResolved,
        }),
      ),
    );
    return [...conversation, ...review].sort((a, b) =>
      a.createdAt.localeCompare(b.createdAt),
    );
  }, [commentsQuery.data, threadsQuery.data, prUrl]);

  if (commentsQuery.isLoading || threadsQuery.isLoading) {
    return (
      <PrSectionHeader
        Icon={ChatCircleIcon}
        title="Comments"
        collapsed
        onToggle={() => {}}
        summary={
          <span className="inline-flex items-center gap-2 text-[11px] text-gray-10">
            <Spinner />
            Loading…
          </span>
        }
      />
    );
  }

  const conversationFailed =
    commentsQuery.isError || commentsQuery.data === null;
  const threadsFailed = threadsQuery.isError;

  if (items.length === 0) {
    // A partial failure with nothing else to show must read as an error —
    // silently hiding the section here would look like "no comments".
    if (conversationFailed || threadsFailed) {
      const detail =
        (commentsQuery.error ?? threadsQuery.error)?.message ?? null;
      return (
        <div className="text-[12px] text-gray-10">
          Couldn't load comments for this pull request.
          {detail && (
            <span className="mt-0.5 block truncate text-(--gray-9) text-[11px]">
              {detail}
            </span>
          )}
        </div>
      );
    }
    return null;
  }

  return (
    <div className="flex flex-col gap-3">
      <PrSectionHeader
        Icon={ChatCircleIcon}
        title="Comments"
        collapsed={collapsed}
        onToggle={() => setCollapsed(!collapsed)}
        summary={
          <span className="text-[11px] text-gray-10 tabular-nums">
            {items.length} comment{items.length === 1 ? "" : "s"}
          </span>
        }
      />
      {!collapsed && (
        <div className="overflow-hidden rounded-md border border-(--gray-5)">
          {items.map((item) => (
            <CommentRow key={item.key} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}

function CommentRow({ item }: { item: CommentItem }) {
  return (
    <div className="flex flex-col gap-1.5 border-b border-b-(--gray-5) px-3 py-2 last:border-b-0">
      <div className="flex min-w-0 items-center gap-2 text-[11px] text-gray-11">
        {item.avatarUrl && (
          <img
            src={item.avatarUrl}
            alt=""
            className="h-4 w-4 shrink-0 rounded-full"
          />
        )}
        <span className="shrink-0 font-medium text-gray-12">{item.author}</span>
        <RelativeTimestamp timestamp={item.createdAt} className="text-[11px]" />
        {item.filePath && (
          <span
            title={item.filePath}
            className="min-w-0 truncate font-mono text-[10px] text-gray-10"
          >
            {item.filePath}
          </span>
        )}
        {item.resolved && (
          <span className="shrink-0 rounded-full bg-(--gray-3) px-1.5 py-px text-[10px] text-gray-10">
            Resolved
          </span>
        )}
        {item.url && (
          <NestedButton
            aria-label="Open comment in GitHub"
            className="ml-auto inline-flex shrink-0 cursor-pointer rounded p-[2px] text-(--gray-9) hover:bg-gray-4"
            onActivate={() => {
              if (item.url) openExternalUrl(item.url);
            }}
          >
            <ArrowSquareOutIcon size={12} />
          </NestedButton>
        )}
      </div>
      <div className="min-w-0 text-pretty break-words text-[12px] text-gray-11 [&_*]:leading-relaxed [&_.rt-Text]:mb-1 [&_li]:mb-0.5 [&_p:last-child]:mb-0">
        <MarkdownRenderer content={item.body} />
      </div>
    </div>
  );
}
