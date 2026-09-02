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
  taskOverrides?: Partial<ActivityTaskLike>;
}) {
  return buildActivityTimeline({
    task: { ...task, ...input.taskOverrides },
    messages: input.messages ?? [],
    commentThreads: input.commentThreads ?? [],
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

  it.each([
    ["an agent", "agent" as const],
    ["a human", "human" as const],
    ["an unattributed author", undefined],
  ])(
    "ignores an unknown event from %s, so the backend can ship first",
    (_name, authorKind) => {
      // A human-authored announcement the client can't parse must not surface as a reply
      // typed by that person; the content is a fixed server string.
      const rows = build({
        messages: [
          {
            id: "m1",
            content: "Commented",
            created_at: "2026-08-01T10:30:00Z",
            ...(authorKind ? { author_kind: authorKind } : {}),
            event: "checks_failed_someday",
            payload: {},
          },
        ],
      });

      expect(rows.map((row) => row.kind)).toEqual(["task_created"]);
    },
  );

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

  it("shows a pull request recorded only on the run's output", () => {
    // Tasks from before the announcements carry the PR nowhere else, and dropping the row
    // hid the pull request from the panel entirely.
    const rows = build({
      taskOverrides: {
        latestRunId: "run-1",
        latestRunPrUrl: "https://github.com/PostHog/posthog/pull/81410",
      },
    });

    expect(rows).toContainEqual(
      expect.objectContaining({
        kind: "run_output_pr",
        prUrl: "https://github.com/PostHog/posthog/pull/81410",
      }),
    );
  });

  it("leaves the run's output alone once the thread announced the pull request", () => {
    const rows = build({
      messages: [
        eventMessage(
          "m1",
          "pr_created",
          { pr_url: "https://github.com/PostHog/posthog/pull/81410" },
          "2026-08-01T11:00:00Z",
        ),
      ],
      taskOverrides: {
        latestRunId: "run-1",
        latestRunPrUrl: "https://github.com/PostHog/posthog/pull/81410",
      },
    });

    expect(rows.filter((row) => row.kind === "run_output_pr")).toHaveLength(0);
  });

  it("keeps every ask for input a run makes, not just the first", () => {
    // The dedupe guard exists for two paths reporting one occurrence. A run that asks
    // twice is two occurrences, and collapsing them hides the second ask.
    const rows = build({
      messages: [
        eventMessage(
          "m1",
          "awaiting_input",
          { run_id: "run-1" },
          "2026-08-01T11:00:00Z",
        ),
        eventMessage(
          "m2",
          "awaiting_input",
          { run_id: "run-1" },
          "2026-08-01T12:00:00Z",
        ),
      ],
    });

    expect(
      rows.filter(
        (row) => row.kind === "event" && row.event.kind === "awaiting_input",
      ),
    ).toHaveLength(2);
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
        runId: null,
        referenceType: null,
        objectKind: null,
      },
    });
  });

  it.each([
    "plan",
    "context",
    "reference",
    "artifact",
    "tree_snapshot",
    "user_attachment",
    "skill_bundle",
  ])(
    "drops non-output %s artifacts from historical timelines",
    (artifactType) => {
      expect(
        parseActivityEvent({
          event: "artifact_created",
          payload: {
            artifact_id: "internal-1",
            name: "checkpoint.index",
            artifact_type: artifactType,
          },
        }),
      ).toBeNull();
    },
  );

  it("keeps PostHog reference artifacts in the timeline", () => {
    expect(
      parseActivityEvent({
        event: "artifact_created",
        payload: {
          artifact_id: "phref-1",
          name: "Checkout funnel",
          artifact_type: "reference",
          reference_type: "posthog_object",
          object_kind: "insight",
          run_id: "run-1",
        },
      }),
    ).toEqual({
      kind: "artifact_created",
      payload: {
        artifactId: "phref-1",
        name: "Checkout funnel",
        artifactType: "reference",
        version: 1,
        runId: "run-1",
        referenceType: "posthog_object",
        objectKind: "insight",
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
    // `commits_pushed` is emitted by a backend layer with no desktop reporter on this
    // branch (that half is deliberately left out), so it is expected ahead of the enum.
    const emittedLater = new Set(["commits_pushed"]);
    const { readFile } = await import("node:fs/promises");
    const models = await readFile(
      new URL("../../../../../tasks/backend/models.py", import.meta.url)
        .pathname,
      "utf8",
    );
    const enumStart = models.indexOf(
      "class TaskActivityEvent(models.TextChoices):",
    );
    // This desktop change ships ahead of the layers that emit the rest of the vocabulary:
    // master's models.py has no TaskActivityEvent enum yet, and only `canvas_created` and
    // `pr_created` arrive as thread messages today. Those two are the contract until the
    // enum exists; rows for the rest parse and stay undrawn until the events show up.
    const backendEvents =
      enumStart === -1
        ? ["canvas_created", "pr_created"]
        : [
            ...models
              .slice(enumStart)
              .slice(0, models.indexOf("class TaskThreadMessage("))
              .matchAll(/^\s{4}[A-Z_]+ = "([a-z_]+)"/gm),
          ].map((match) => match[1]);
    // An event neither side has shipped yet is expectable either direction, not drift.
    const pendingBackendEvents =
      enumStart === -1
        ? new Set(
            ACTIVITY_EVENTS.filter((event) => !backendEvents.includes(event)),
          )
        : emittedLater;

    expect(
      [...ACTIVITY_EVENTS]
        .filter((event) => !pendingBackendEvents.has(event))
        .sort(),
    ).toEqual(backendEvents.sort());
  });
});

describe("commits pushed", () => {
  it("reads a push into a row with its commits", () => {
    expect(
      parseActivityEvent({
        event: "commits_pushed",
        payload: {
          run_id: "run-1",
          branch: "shy/x",
          repository: "PostHog/posthog",
          total: 3,
          commits: [
            { sha: "a41c9e2", subject: "feat: one", url: "https://x/1" },
            { sha: "7d0be55", subject: "feat: two", url: null },
          ],
        },
      }),
    ).toEqual({
      kind: "commits_pushed",
      payload: {
        runId: "run-1",
        branch: "shy/x",
        repository: "PostHog/posthog",
        total: 3,
        commits: [
          { sha: "a41c9e2", subject: "feat: one", url: "https://x/1" },
          { sha: "7d0be55", subject: "feat: two", url: null },
        ],
      },
    });
  });

  it("drops a push with no readable commit, which cannot be drawn", () => {
    expect(
      parseActivityEvent({
        event: "commits_pushed",
        payload: { run_id: "run-1", commits: [{ subject: "no sha" }] },
      }),
    ).toBeNull();
  });
});

describe("comment events", () => {
  it("reads identity-only comment events, and drops one with no thread to open", () => {
    expect(
      parseActivityEvent({
        event: "comment_added",
        payload: {
          comment_id: "c-1",
          root_comment_id: "c-1",
          scope: "task_artifact",
          item_id: "artifact-1",
        },
      }),
    ).toEqual({
      kind: "comment_added",
      payload: {
        commentId: "c-1",
        rootCommentId: "c-1",
        scope: "task_artifact",
        itemId: "artifact-1",
        targetName: null,
      },
    });
    expect(
      parseActivityEvent({
        event: "comment_state_changed",
        payload: {
          comment_id: "c-2",
          root_comment_id: "c-1",
          scope: "task",
          item_id: "task-1",
          state: "resolved",
        },
      }),
    ).toMatchObject({
      kind: "comment_state_changed",
      payload: { rootCommentId: "c-1", state: "resolved" },
    });
    expect(
      parseActivityEvent({ event: "comment_added", payload: {} }),
    ).toBeNull();
    expect(
      parseActivityEvent({
        event: "comment_state_changed",
        payload: { root_comment_id: "c-1", state: "archived" },
      }),
    ).toBeNull();
  });

  it("keys a push on its head SHA, so a retried report is one row", () => {
    const push = (id: string) =>
      eventMessage(
        id,
        "commits_pushed",
        {
          run_id: "run-1",
          branch: "shy/x",
          total: 1,
          commits: [{ sha: "head1", subject: "feat: one" }],
        },
        "2026-08-01T10:30:00Z",
      );

    const rows = build({ messages: [push("m1"), push("m2")] });

    expect(rows.filter((row) => row.kind === "event")).toHaveLength(1);
  });
});
