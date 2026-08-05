import type { ResourceComment } from "@posthog/api-client/posthog-client";
import {
  type CommentContext,
  isThreadResolved,
  parseCommentContext,
} from "@posthog/core/comments/anchors";

export type HighlightResolution = "exact" | "reanchored" | "orphaned";
export type CommentLocateRequest = { id: string; nonce: number };

export function readCommentContext(
  comment: ResourceComment,
): CommentContext | null {
  return parseCommentContext(comment.item_context);
}

export type CommentThread = {
  root: ResourceComment;
  replies: ResourceComment[];
  resolved: boolean;
};

export function buildCommentThreads(
  comments: ResourceComment[],
): CommentThread[] {
  const roots: ResourceComment[] = [];
  const repliesByRoot = new Map<string, ResourceComment[]>();
  for (const comment of comments) {
    if (!comment.source_comment) {
      roots.push(comment);
      continue;
    }
    const replies = repliesByRoot.get(comment.source_comment) ?? [];
    replies.push(comment);
    repliesByRoot.set(comment.source_comment, replies);
  }
  return roots
    .sort((a, b) => a.created_at.localeCompare(b.created_at))
    .map((root) => {
      const replies = repliesByRoot.get(root.id) ?? [];
      return {
        root,
        replies,
        resolved: isThreadResolved(root, replies),
      };
    });
}
