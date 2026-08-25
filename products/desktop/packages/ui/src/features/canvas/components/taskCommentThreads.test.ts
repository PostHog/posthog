import type { ResourceComment } from "@posthog/api-client/posthog-client";
import type { PrConversationComment, PrReviewThread } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import type { CommentSource } from "./taskArtifactRows";
import {
  byNewestThread,
  prCommentThreads,
  resourceCommentThreads,
  threadSourceOptions,
} from "./taskCommentThreads";

const fileSource: CommentSource = {
  kind: "file",
  target: { scope: "task_artifact", itemId: "a" },
  name: "report.md",
  runId: "run-1",
};
const taskSource: CommentSource = {
  kind: "task",
  target: { scope: "task", itemId: "task-1" },
  name: "This task",
};

function comment(overrides: Partial<ResourceComment>): ResourceComment {
  return {
    id: "c1",
    created_by: null,
    content: "hi",
    created_at: "2024-01-01T00:00:00Z",
    item_id: "a",
    item_context: { anchor: { kind: "document" } },
    scope: "task_artifact",
    source_comment: null,
    ...overrides,
  } as ResourceComment;
}

describe("resourceCommentThreads", () => {
  it("keeps only threads whose resource is present, tagged with it", () => {
    const threads = resourceCommentThreads(
      [
        comment({ id: "c1", item_id: "a", content: "root" }),
        comment({
          id: "r1",
          item_id: "a",
          source_comment: "c1",
          content: "reply",
          created_at: "2024-01-01T00:01:00Z",
        }),
        comment({ id: "orphan", item_id: "gone", content: "no source" }),
      ],
      [fileSource, taskSource],
    );

    expect(threads).toHaveLength(1);
    expect(threads[0].sourceKind).toBe("file");
    expect(threads[0].sourceLabel).toBe("report.md");
    expect(threads[0].entries.map((entry) => entry.body)).toEqual([
      "root",
      "reply",
    ]);
    // The reply is newer, but ordering follows the root: replying must not move
    // the thread out from under whoever is reading it.
    expect(threads[0].startedAt).toBe("2024-01-01T00:00:00Z");
  });

  // A resolve/reopen reply is thread state, not something anyone said.
  it("drops thread-state replies from the visible entries", () => {
    const threads = resourceCommentThreads(
      [
        comment({ id: "c1", content: "root" }),
        comment({
          id: "state",
          source_comment: "c1",
          content: "Resolved this thread",
          created_at: "2024-01-01T00:02:00Z",
          item_context: {
            anchor: { kind: "document" },
            threadState: "resolved",
          },
        }),
      ],
      [fileSource],
    );

    expect(threads[0].resolved).toBe(true);
    expect(threads[0].entries).toHaveLength(1);
    expect(threads[0].startedAt).toBe("2024-01-01T00:00:00Z");
  });
});

describe("prCommentThreads", () => {
  const reviewThread: PrReviewThread = {
    nodeId: "node-1",
    isResolved: true,
    rootId: 501,
    filePath: "src/App.tsx",
    comments: [
      {
        id: 501,
        body: "root",
        path: "src/App.tsx",
        line: 3,
        original_line: null,
        side: "RIGHT",
        start_line: null,
        start_side: null,
        diff_hunk: "",
        user: { login: "octo", avatar_url: "http://x/a.png" },
        created_at: "2024-01-01T00:00:00Z",
        updated_at: "2024-01-01T00:00:00Z",
        subject_type: "line",
      },
      {
        id: 502,
        body: "reply",
        path: "src/App.tsx",
        line: 3,
        original_line: null,
        side: "RIGHT",
        start_line: null,
        start_side: null,
        diff_hunk: "",
        user: { login: "octo", avatar_url: "" },
        created_at: "2024-01-01T00:05:00Z",
        updated_at: "2024-01-01T00:05:00Z",
        subject_type: "line",
      },
    ],
  };
  const conversation: PrConversationComment = {
    id: 900,
    author: "octo",
    avatarUrl: null,
    body: "lgtm",
    createdAt: "2024-01-02T00:00:00Z",
    url: "https://github.com/a/b/pull/7#c",
  };

  it("carries review-thread replies, resolution and the reply/resolve ids", () => {
    const [thread] = prCommentThreads("url", "PR #7", [reviewThread], []);

    expect(thread.entries.map((entry) => entry.body)).toEqual([
      "root",
      "reply",
    ]);
    expect(thread.resolved).toBe(true);
    expect(thread.origin).toMatchObject({
      kind: "pr-review",
      rootCommentId: 501,
      threadNodeId: "node-1",
      filePath: "src/App.tsx",
    });
    // The thread's own start, so a reply can't re-rank it in the list.
    expect(thread.startedAt).toBe("2024-01-01T00:00:00Z");
  });

  it("makes each conversation comment its own unresolvable thread", () => {
    const [thread] = prCommentThreads("url", "PR #7", [], [conversation]);

    expect(thread.entries).toHaveLength(1);
    expect(thread.resolved).toBe(false);
    expect(thread.origin.kind).toBe("pr-conversation");
  });

  it("omits GitHub bot comments without hiding human threads", () => {
    const botRoot = {
      ...reviewThread,
      nodeId: "bot-root",
      comments: reviewThread.comments.map((comment) => ({
        ...comment,
        user: { ...comment.user, isBot: true },
      })),
    };
    const humanRootWithBotReply = {
      ...reviewThread,
      nodeId: "human-root",
      comments: [
        reviewThread.comments[0],
        {
          ...reviewThread.comments[1],
          user: { ...reviewThread.comments[1].user, isBot: true },
        },
      ],
    };

    const threads = prCommentThreads(
      "url",
      "PR #7",
      [botRoot, humanRootWithBotReply],
      [conversation, { ...conversation, id: 901, isBot: true }],
    );

    expect(threads).toHaveLength(2);
    expect(
      threads.map((thread) => thread.entries.map((entry) => entry.body)),
    ).toEqual([["root"], ["lgtm"]]);
  });
});

describe("threadSourceOptions / byNewestThread", () => {
  it("lists each source once and sorts newest first", () => {
    const threads = [
      ...resourceCommentThreads(
        [comment({ id: "c1", content: "old" })],
        [fileSource],
      ),
      ...prCommentThreads(
        "url",
        "PR #7",
        [],
        [
          {
            id: 1,
            author: "octo",
            avatarUrl: null,
            body: "new",
            createdAt: "2025-01-01T00:00:00Z",
            url: null,
          },
        ],
      ),
    ].sort(byNewestThread);

    expect(threads[0].entries[0].body).toBe("new");
    // Options follow list order, which is newest-first, and carry the kind so
    // the filter can show a matching icon.
    expect(
      threadSourceOptions(threads).map((option) => [option.label, option.kind]),
    ).toEqual([
      ["PR #7", "pr"],
      ["report.md", "file"],
    ]);
  });

  // The task is the one source every task has, so it sits at the top of the
  // filter regardless of when it was last touched.
  it("pins the task source first, keeping the rest newest-first", () => {
    const threads = [
      ...resourceCommentThreads(
        [
          comment({
            id: "f1",
            item_id: "a",
            content: "file",
            created_at: "2025-01-01T00:00:00Z",
          }),
          comment({
            id: "t1",
            item_id: "task-1",
            scope: "task",
            content: "task",
            created_at: "2024-01-01T00:00:00Z",
          }),
        ],
        [fileSource, taskSource],
      ),
    ].sort(byNewestThread);

    expect(threadSourceOptions(threads).map((option) => option.kind)).toEqual([
      "task",
      "file",
    ]);
  });
});
