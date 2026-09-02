import type { ResourceComment } from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import { buildCommentThreads } from "./commentViewTypes";

function comment(
  id: string,
  createdAt: string,
  sourceComment: string | null = null,
): ResourceComment {
  return {
    id,
    created_at: createdAt,
    source_comment: sourceComment,
    content: id,
    scope: "task",
    item_id: "task-1",
    item_context: { anchor: { kind: "document" } },
    created_by: null,
    deleted: false,
    is_task: false,
    completed_at: null,
    completed_by: null,
  } as ResourceComment;
}

describe("buildCommentThreads", () => {
  it("orders replies by when they were sent regardless of API order", () => {
    const root = comment("root", "2026-08-04T10:00:00Z");
    const olderReply = comment("older-reply", "2026-08-04T10:05:00Z", root.id);
    const newestReply = comment(
      "newest-reply",
      "2026-08-04T10:10:00Z",
      root.id,
    );

    const [thread] = buildCommentThreads([newestReply, root, olderReply]);

    expect(thread?.replies.map((reply) => reply.id)).toEqual([
      "older-reply",
      "newest-reply",
    ]);
  });
});
