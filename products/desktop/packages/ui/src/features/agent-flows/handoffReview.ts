import type { ResourceComment } from "@posthog/api-client/posthog-client";
import { parseCommentContext } from "@posthog/core/comments/anchors";
import {
  type AgentFlowReview,
  type AgentFlowReviewComment,
  agentFlowReviewSchema,
} from "@posthog/shared";
import { buildCommentThreads } from "@posthog/ui/features/sessions/components/commentViewTypes";

export function readFlowReview(value: unknown): AgentFlowReview | null {
  const parsed = agentFlowReviewSchema.safeParse(value);
  return parsed.success ? parsed.data : null;
}

/** Open comment threads on the document, as the flow reads them. */
export function toReviewComments(
  comments: ResourceComment[],
): AgentFlowReviewComment[] {
  return buildCommentThreads(comments)
    .filter((thread) => !thread.resolved)
    .flatMap((thread) => {
      const anchor = parseCommentContext(thread.root.item_context)?.anchor;
      const quote = anchor?.kind === "text" ? anchor.quote : undefined;
      const body = [thread.root, ...thread.replies]
        .map((comment) => comment.content?.trim() ?? "")
        .filter(Boolean)
        .join("\n");
      if (!body) return [];
      return [quote ? { quote, body } : { body }];
    });
}
