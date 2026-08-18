import { describe, expect, it } from "vitest";
import {
  buildCanvasTaskSummaries,
  type CanvasTaskSession,
  type CanvasTaskSource,
} from "./canvasTasks";
import { canvasTasksResultSchema } from "./freeformSchemas";

function makeTask(overrides: Partial<CanvasTaskSource> = {}): CanvasTaskSource {
  return {
    id: "task-1",
    title: "Fix login redirect",
    repository: "posthog/code",
    created_at: "2026-08-18T10:00:00Z",
    updated_at: "2026-08-18T11:00:00Z",
    latest_run: null,
    ...overrides,
  };
}

function makeSession(
  overrides: Partial<CanvasTaskSession> = {},
): CanvasTaskSession {
  return {
    taskId: "task-1",
    status: "connected",
    pendingPermissions: { size: 0 },
    isPromptPending: false,
    ...overrides,
  };
}

describe("buildCanvasTaskSummaries", () => {
  it("returns idle for a task with no session and no run", () => {
    const { tasks } = buildCanvasTaskSummaries([makeTask()], {});
    expect(tasks).toHaveLength(1);
    expect(tasks[0]).toMatchObject({
      id: "task-1",
      title: "Fix login redirect",
      status: "idle",
      runStatus: null,
      environment: null,
      repository: "posthog/code",
      prUrl: null,
      needsPermission: false,
      isGenerating: false,
      createdAt: "2026-08-18T10:00:00Z",
      updatedAt: "2026-08-18T11:00:00Z",
    });
  });

  it("derives live status from the task's session (keyed by run id, matched via taskId)", () => {
    const { tasks } = buildCanvasTaskSummaries([makeTask()], {
      "run-9": makeSession({ pendingPermissions: { size: 1 } }),
    });
    expect(tasks[0].status).toBe("waiting");
    expect(tasks[0].needsPermission).toBe(true);
  });

  it("reports running + isGenerating while a connected session has a prompt in flight", () => {
    const { tasks } = buildCanvasTaskSummaries([makeTask()], {
      "run-9": makeSession({ isPromptPending: true }),
    });
    expect(tasks[0].status).toBe("running");
    expect(tasks[0].isGenerating).toBe(true);
  });

  it.each([
    { runStatus: "in_progress", expected: "running" },
    { runStatus: "queued", expected: "running" },
    { runStatus: "completed", expected: "completed" },
    { runStatus: "failed", expected: "error" },
    { runStatus: "cancelled", expected: "error" },
    { runStatus: "not_started", expected: "idle" },
  ] as const)(
    "falls back to the run status when there is no live session ($runStatus → $expected)",
    ({ runStatus, expected }) => {
      const { tasks } = buildCanvasTaskSummaries(
        [makeTask({ latest_run: { status: runStatus } })],
        {},
      );
      expect(tasks[0].status).toBe(expected);
      expect(tasks[0].runStatus).toBe(runStatus);
    },
  );

  it("prefers the live session over the stale run status", () => {
    const { tasks } = buildCanvasTaskSummaries(
      [makeTask({ latest_run: { status: "completed" } })],
      { "run-9": makeSession({ isPromptPending: true }) },
    );
    expect(tasks[0].status).toBe("running");
  });

  it.each([
    { runStatus: "completed", expected: "completed" },
    { runStatus: "failed", expected: "error" },
    { runStatus: "cancelled", expected: "error" },
  ] as const)(
    "prefers the terminal run status ($runStatus) over a session that is merely idle",
    ({ runStatus, expected }) => {
      // A local session stays connected after its prompt finishes; the board
      // should show the landed outcome, not "idle".
      const { tasks } = buildCanvasTaskSummaries(
        [makeTask({ latest_run: { status: runStatus } })],
        { "run-9": makeSession() },
      );
      expect(tasks[0].status).toBe(expected);
    },
  );

  it("keeps an idle session idle while the run record still claims in_progress", () => {
    // The live session is the fresher signal — a stale in_progress run record
    // must not resurrect "running".
    const { tasks } = buildCanvasTaskSummaries(
      [makeTask({ latest_run: { status: "in_progress" } })],
      { "run-9": makeSession() },
    );
    expect(tasks[0].status).toBe("idle");
  });

  it("reads the PR url from the run output, falling back to the session's cloud output", () => {
    const fromRun = buildCanvasTaskSummaries(
      [
        makeTask({
          latest_run: {
            status: "completed",
            output: { pr_url: "https://github.com/posthog/code/pull/1" },
          },
        }),
      ],
      {},
    );
    expect(fromRun.tasks[0].prUrl).toBe(
      "https://github.com/posthog/code/pull/1",
    );

    const fromSession = buildCanvasTaskSummaries([makeTask()], {
      "run-9": makeSession({
        cloudOutput: { pr_url: "https://github.com/posthog/code/pull/2" },
      }),
    });
    expect(fromSession.tasks[0].prUrl).toBe(
      "https://github.com/posthog/code/pull/2",
    );
  });

  it("surfaces the run environment", () => {
    const { tasks } = buildCanvasTaskSummaries(
      [
        makeTask({
          latest_run: { status: "in_progress", environment: "cloud" },
        }),
      ],
      {},
    );
    expect(tasks[0].environment).toBe("cloud");
  });

  it("sorts by updated_at, most recent first", () => {
    const { tasks } = buildCanvasTaskSummaries(
      [
        makeTask({ id: "old", updated_at: "2026-08-18T09:00:00Z" }),
        makeTask({ id: "new", updated_at: "2026-08-18T12:00:00Z" }),
      ],
      {},
    );
    expect(tasks.map((t) => t.id)).toEqual(["new", "old"]);
  });

  it("applies the requested limit after sorting", () => {
    const { tasks } = buildCanvasTaskSummaries(
      [
        makeTask({ id: "old", updated_at: "2026-08-18T09:00:00Z" }),
        makeTask({ id: "new", updated_at: "2026-08-18T12:00:00Z" }),
      ],
      {},
      { limit: 1 },
    );
    expect(tasks.map((t) => t.id)).toEqual(["new"]);
  });

  it("caps at the default limit when none is given", () => {
    const many = Array.from({ length: 60 }, (_, i) =>
      makeTask({ id: `task-${i}` }),
    );
    const { tasks } = buildCanvasTaskSummaries(many, {});
    expect(tasks).toHaveLength(50);
  });

  it("produces output that satisfies the wire schema", () => {
    const result = buildCanvasTaskSummaries([makeTask({ repository: null })], {
      "run-9": makeSession(),
    });
    expect(canvasTasksResultSchema.safeParse(result).success).toBe(true);
  });
});
