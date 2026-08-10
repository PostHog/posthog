import {
  ACTIVITY_EVENTS,
  parseActivityEvent,
} from "@posthog/core/canvas/activityEvents";
import {
  type ActivityTaskLike,
  buildActivityTimeline,
  type CommentThreadLike,
} from "@posthog/core/canvas/activityTimeline";
import type { ThreadMessageLike } from "@posthog/core/canvas/threadTimeline";
import { describe, expect, it } from "vitest";

const task: ActivityTaskLike = {
  id: "task-1",
  createdAt: "2026-08-01T10:00:00Z",
  updatedAt: "2026-08-01T12:00:00Z",
};

function eventMessage(
  id: string,
  event: string,
  payload: Record<string, unknown>,
  createdAt: string,
): ThreadMessageLike {
  return {
    id,
    content: "",
    created_at: createdAt,
    author_kind: "agent",
    event,
    payload,
  };
}

function thread(overrides: Partial<CommentThreadLike> = {}): CommentThreadLike {
  return {
    id: "thread-1",
    lastActivityAt: "2026-08-01T11:00:00Z",
    mentionedUserIds: [],
    resolved: false,
    stateEvent: null,
    ...overrides,
  };
}

function build(input: {
  messages?: ThreadMessageLike[];
  commentThreads?: CommentThreadLike[];
  commentsEnabled?: boolean;
  taskOverrides?: Partial<ActivityTaskLike>;
}) {
  return buildActivityTimeline({
    task: { ...task, ...input.taskOverrides },
    messages: input.messages ?? [],
    commentThreads: input.commentThreads ?? [],
    commentsEnabled: input.commentsEnabled,
  });
}

describe("activity timeline", () => {
  it("leads with the task's creation", () => {
    const rows = build({});

    expect(rows.map((row) => row.kind)).toEqual(["task_created"]);
  });

  it("orders every source by time", () => {
    const rows = build({
      messages: [
        eventMessage(
          "m2",
          "run_started",
          { run_id: "run-1" },
          "2026-08-01T10:30:00Z",
        ),
        {
          id: "m1",
          content: "what about mobile?",
          created_at: "2026-08-01T10:15:00Z",
        },
      ],
      commentThreads: [thread()],
    });

    expect(rows.map((row) => row.key)).toEqual([
      "task-created",
      "message-m1",
      "event-m2",
      "comment-thread-1",
    ]);
  });

  it("places a comment thread at its newest activity, not its start", () => {
    // A thread that keeps getting replies has to stay one row that moves, or a five-reply
    // exchange pushes everything else off the panel.
    const rows = build({
      messages: [
        eventMessage(
          "m1",
          "run_started",
          { run_id: "run-1" },
          "2026-08-01T13:00:00Z",
        ),
      ],
      commentThreads: [thread({ lastActivityAt: "2026-08-01T14:00:00Z" })],
    });

    expect(rows.map((row) => row.kind)).toEqual([
      "task_created",
      "event",
      "comment",
    ]);
  });

  it("gives resolve its own row after the thread", () => {
    const rows = build({
      commentThreads: [
        thread({
          resolved: true,
          stateEvent: { state: "resolved", createdAt: "2026-08-01T11:30:00Z" },
        }),
      ],
    });

    expect(rows.map((row) => row.kind)).toEqual([
      "task_created",
      "comment",
      "comment_state",
    ]);
  });

  it("drops the comment feed when comments are off", () => {
    const rows = build({
      commentThreads: [
        thread({
          stateEvent: { state: "resolved", createdAt: "2026-08-01T11:30:00Z" },
        }),
      ],
      commentsEnabled: false,
    });

    expect(rows.map((row) => row.kind)).toEqual(["task_created"]);
  });

  it("keeps one row when two paths announced the same pull request", () => {
    // The agent's own output and the GitHub webhook backstop can both observe a PR.
    const rows = build({
      messages: [
        eventMessage(
          "m1",
          "pr_created",
          { pr_url: "https://github.com/posthog/posthog/pull/1" },
          "2026-08-01T10:30:00Z",
        ),
        eventMessage(
          "m2",
          "pr_created",
          { pr_url: "https://github.com/posthog/posthog/pull/1" },
          "2026-08-01T10:31:00Z",
        ),
      ],
    });

    expect(rows.filter((row) => row.kind === "event")).toHaveLength(1);
  });

  it("ignores events it doesn't know, so the backend can ship first", () => {
    const rows = build({
      messages: [
        eventMessage("m1", "checks_failed_someday", {}, "2026-08-01T10:30:00Z"),
      ],
    });

    expect(rows.map((row) => row.kind)).toEqual(["task_created"]);
  });

  it("numbers runs over the feed, since the backend cannot number them", () => {
    // Counting runs server-side races two concurrent creations onto one number; the ordered
    // feed can only be read one way.
    const rows = build({
      messages: [
        eventMessage(
          "m1",
          "run_started",
          { run_id: "run-1" },
          "2026-08-01T10:30:00Z",
        ),
        eventMessage(
          "m2",
          "run_started",
          { run_id: "run-2" },
          "2026-08-01T11:30:00Z",
        ),
      ],
    });

    expect(
      rows.flatMap((row) => (row.kind === "event" ? [row.runOrdinal] : [])),
    ).toEqual([1, 2]);
  });

  it("derives an ending for tasks with no failure event", () => {
    const rows = build({
      taskOverrides: { latestRunStatus: "completed", latestRunId: "run-1" },
    });

    expect(rows.at(-1)).toMatchObject({
      kind: "run_status",
      status: "completed",
    });
  });

  it("prefers the failure event over the derived ending", () => {
    // The event carries the reason, which is the whole point of having it.
    const rows = build({
      messages: [
        eventMessage(
          "m1",
          "run_failed",
          { run_id: "run-1", error_summary: "pnpm build failed" },
          "2026-08-01T11:00:00Z",
        ),
      ],
      taskOverrides: { latestRunStatus: "failed", latestRunId: "run-1" },
    });

    expect(rows.filter((row) => row.kind === "run_status")).toHaveLength(0);
    expect(rows.at(-1)).toMatchObject({ kind: "event" });
  });
});

describe("activity events", () => {
  it("reads a run_started payload", () => {
    expect(
      parseActivityEvent({
        event: "run_started",
        payload: { run_id: "run-1", environment: "cloud", branch: "casey/x" },
      }),
    ).toEqual({
      kind: "run_started",
      payload: { runId: "run-1", environment: "cloud", branch: "casey/x" },
    });
  });

  it("falls back rather than rendering a partial payload", () => {
    expect(
      parseActivityEvent({ event: "artifact_created", payload: {} }),
    ).toEqual({
      kind: "artifact_created",
      payload: {
        artifactId: "",
        name: "Artifact",
        artifactType: "",
        version: 1,
      },
    });
  });

  it("drops a pull request event with no url, since it can't be opened", () => {
    expect(parseActivityEvent({ event: "pr_merged", payload: {} })).toBeNull();
  });

  it.each(["", "turn_complete", "something_new"])(
    "returns null for %s",
    (event) => {
      expect(parseActivityEvent({ event, payload: {} })).toBeNull();
    },
  );

  it("matches the backend vocabulary", async () => {
    // The two lists are one contract: adding an event on one side only is a silent gap.
    const { readFile } = await import("node:fs/promises");
    const models = await readFile(
      new URL("../../../../../tasks/backend/models.py", import.meta.url)
        .pathname,
      "utf8",
    );
    const block = models.slice(
      models.indexOf("class TaskActivityEvent(models.TextChoices):"),
    );
    const backendEvents = [
      ...block
        .slice(0, block.indexOf("class TaskThreadMessage("))
        .matchAll(/^\s{4}[A-Z_]+ = "([a-z_]+)"/gm),
    ].map((match) => match[1]);

    expect([...ACTIVITY_EVENTS].sort()).toEqual(backendEvents.sort());
  });
});
