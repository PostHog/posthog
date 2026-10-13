import type { ResourceComment } from "@posthog/api-client/posthog-client";
import { commentTargetKey } from "@posthog/core/comments/anchors";
import type { PrConversationComment, PrReviewThread } from "@posthog/shared";
import type { UserBasic } from "@posthog/shared/domain-types";
import type { CommentSource } from "@posthog/ui/features/canvas/components/taskArtifactRows";
import {
  buildCommentThreads,
  readCommentContext,
} from "@posthog/ui/features/sessions/components/commentViewTypes";

export type CommentEntry = {
  id: string;
  authorName: string;
  /** A PostHog author, whose avatar and hue are the ones they have app-wide. */
  user: UserBasic | null;
  /** A GitHub author, who only comes with an avatar url. */
  avatarUrl: string | null;
  createdAt: string;
  body: string;
  /** PostHog comments carry @mention markup; GitHub bodies are markdown. */
  format: "mentions" | "markdown";
};

/** How a thread is opened, replied to and resolved — one case per backend. */
export type ThreadOrigin =
  | {
      kind: "resource";
      source: CommentSource;
      /** The root comment, needed to reply to and resolve the thread. */
      root: ResourceComment;
    }
  | {
      kind: "pr-review";
      prUrl: string;
      filePath: string;
      /** GitHub replies target a comment id, resolution a thread node id. */
      rootCommentId: number;
      threadNodeId: string;
    }
  | { kind: "pr-conversation"; prUrl: string; url: string | null };

/**
 * One thread in the task's comment list, whichever system it came from. The
 * list renders and sorts these; only replying, resolving and opening still care
 * where a thread lives, which is what `origin` carries.
 */
export type TaskCommentThread = {
  /** Stable across refetches: the scroll target and React key. */
  id: string;
  /** Groups threads for the source filter. */
  sourceKey: string;
  sourceLabel: string;
  sourceKind: "file" | "canvas" | "task" | "posthog_object" | "pr";
  entries: CommentEntry[];
  resolved: boolean;
  /** When the thread was opened, for ordering the list. Ordering on the newest
   *  reply instead would re-rank a thread the moment someone replies to it. */
  startedAt: string;
  origin: ThreadOrigin;
};

function resourceAuthorName(comment: ResourceComment): string {
  const user = comment.created_by;
  if (!user) return "Unknown user";
  return (
    [user.first_name, user.last_name].filter(Boolean).join(" ") || user.email
  );
}

function resourceEntry(comment: ResourceComment): CommentEntry {
  return {
    id: comment.id,
    authorName: resourceAuthorName(comment),
    user: comment.created_by,
    avatarUrl: null,
    createdAt: comment.created_at,
    body: comment.content ?? "",
    format: "mentions",
  };
}

/** The task's own comment threads, tagged with the resource they belong to. */
export function resourceCommentThreads(
  comments: ResourceComment[],
  sources: CommentSource[],
): TaskCommentThread[] {
  const byItemId = new Map<string, CommentSource>();
  for (const source of sources) byItemId.set(source.target.itemId, source);

  return buildCommentThreads(comments).flatMap((thread) => {
    const source = thread.root.item_id
      ? byItemId.get(thread.root.item_id)
      : undefined;
    if (!source) return [];
    // A resolve/reopen reply is thread state, not something anyone said.
    const visibleReplies = thread.replies.filter(
      (reply) => !readCommentContext(reply)?.threadState,
    );
    return [
      {
        id: thread.root.id,
        sourceKey: commentTargetKey(source.target),
        sourceLabel: source.name,
        sourceKind: source.kind,
        entries: [thread.root, ...visibleReplies].map(resourceEntry),
        resolved: thread.resolved,
        startedAt: thread.root.created_at,
        origin: { kind: "resource", source, root: thread.root },
      },
    ];
  });
}

/**
 * A PR's comments as threads. Inline review threads keep their replies and can
 * be resolved; conversation comments (issue chatter, review summaries) are each
 * a thread of one, since GitHub gives them neither replies nor resolution.
 */
export function prCommentThreads(
  prUrl: string,
  prLabel: string,
  reviewThreads: PrReviewThread[],
  conversation: PrConversationComment[],
): TaskCommentThread[] {
  const threads: TaskCommentThread[] = reviewThreads.flatMap((thread) => {
    const root = thread.comments[0];
    if (!root) return [];
    const humanComments = thread.comments.filter(
      (comment) => !comment.user.isBot,
    );
    if (humanComments.length === 0) return [];
    return [
      {
        id: `pr-review-${thread.rootId}`,
        sourceKey: prUrl,
        sourceLabel: prLabel,
        sourceKind: "pr" as const,
        entries: humanComments.map((comment) => ({
          id: `pr-comment-${comment.id}`,
          authorName: comment.user.login,
          user: null,
          avatarUrl: comment.user.avatar_url || null,
          createdAt: comment.created_at,
          body: comment.body,
          format: "markdown" as const,
        })),
        resolved: thread.isResolved,
        // The visible root: a bot may have opened the thread, and bots are filtered out.
        startedAt: humanComments[0].created_at,
        origin: {
          kind: "pr-review" as const,
          prUrl,
          filePath: thread.filePath,
          rootCommentId: thread.rootId,
          threadNodeId: thread.nodeId,
        },
      },
    ];
  });

  for (const comment of conversation) {
    if (comment.isBot) continue;
    threads.push({
      // Conversation items mix issue comments and review summaries, whose ids
      // come from different GitHub id spaces — key on the timestamp too.
      id: `pr-conversation-${comment.id}-${comment.createdAt}`,
      sourceKey: prUrl,
      sourceLabel: prLabel,
      sourceKind: "pr",
      entries: [
        {
          id: `pr-conversation-${comment.id}`,
          authorName: comment.author,
          user: null,
          avatarUrl: comment.avatarUrl,
          createdAt: comment.createdAt,
          body: comment.body,
          format: "markdown",
        },
      ],
      resolved: false,
      startedAt: comment.createdAt,
      origin: { kind: "pr-conversation", prUrl, url: comment.url },
    });
  }

  return threads;
}

export function byNewestThread(
  a: TaskCommentThread,
  b: TaskCommentThread,
): number {
  // Total, so threads opened in the same second can't swap places between renders.
  return b.startedAt.localeCompare(a.startedAt) || a.id.localeCompare(b.id);
}

export type SourceKind = TaskCommentThread["sourceKind"];
export type ThreadSourceOption = {
  key: string;
  label: string;
  kind: SourceKind;
  count: number;
};

/**
 * The available sources for the source filter, including those without a
 * thread yet. The task itself sits at the top because every task has one.
 */
export function threadSourceOptions(
  threads: TaskCommentThread[],
  availableSources: Omit<ThreadSourceOption, "count">[] = [],
): ThreadSourceOption[] {
  const byKey = new Map<string, ThreadSourceOption>(
    availableSources.map((source) => [source.key, { ...source, count: 0 }]),
  );
  for (const thread of threads) {
    const source = byKey.get(thread.sourceKey);
    if (!source) {
      byKey.set(thread.sourceKey, {
        key: thread.sourceKey,
        label: thread.sourceLabel,
        kind: thread.sourceKind,
        count: 1,
      });
    } else {
      source.count += 1;
    }
  }
  return [...byKey.values()].sort(
    (a, b) => Number(b.kind === "task") - Number(a.kind === "task"),
  );
}
