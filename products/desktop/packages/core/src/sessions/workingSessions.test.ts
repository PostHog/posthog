import { describe, expect, it } from "vitest";
import {
  computeWorkingLocalSessionsSignature,
  listWorkingLocalSessions,
  type WorkingSessionFields,
} from "./workingSessions";

function session(
  overrides: Partial<WorkingSessionFields> & { taskRunId: string },
): WorkingSessionFields {
  return {
    taskId: `task-${overrides.taskRunId}`,
    taskTitle: `Title ${overrides.taskRunId}`,
    isPromptPending: true,
    isCompacting: false,
    pendingPermissions: new Map(),
    messageQueue: [],
    startedAt: 0,
    ...overrides,
  };
}

function queued(): WorkingSessionFields["messageQueue"] {
  return [{ id: "q1", content: "and run the tests", queuedAt: 0 }];
}

describe("workingSessions", () => {
  it.each([
    {
      name: "includes a local session with a prompt in flight",
      sessions: [session({ taskRunId: "a" })],
      expectedTaskRunIds: ["a"],
    },
    {
      name: "excludes an idle local session",
      sessions: [session({ taskRunId: "a", isPromptPending: false })],
      expectedTaskRunIds: [],
    },
    {
      name: "excludes a cloud session even while its prompt is in flight",
      sessions: [session({ taskRunId: "a", isCloud: true })],
      expectedTaskRunIds: [],
    },
    {
      name: "includes a session whose turn ended with messages still queued",
      sessions: [
        session({
          taskRunId: "a",
          isPromptPending: false,
          messageQueue: queued(),
        }),
      ],
      expectedTaskRunIds: ["a"],
    },
    {
      name: "includes a compacting session",
      sessions: [
        session({ taskRunId: "a", isPromptPending: false, isCompacting: true }),
      ],
      expectedTaskRunIds: ["a"],
    },
    {
      name: "includes a session waiting on a permission answer",
      sessions: [
        session({
          taskRunId: "a",
          isPromptPending: false,
          pendingPermissions: new Map([["tool-1", {} as never]]),
        }),
      ],
      expectedTaskRunIds: ["a"],
    },
    {
      name: "excludes a cloud session with messages still queued",
      sessions: [
        session({
          taskRunId: "a",
          isPromptPending: false,
          isCloud: true,
          messageQueue: queued(),
        }),
      ],
      expectedTaskRunIds: [],
    },
    {
      name: "keeps only the working local session out of a mixed set",
      sessions: [
        session({ taskRunId: "a", isCloud: true }),
        session({ taskRunId: "b" }),
        session({ taskRunId: "c", isPromptPending: false }),
      ],
      expectedTaskRunIds: ["b"],
    },
    {
      name: "orders by start time",
      sessions: [
        session({ taskRunId: "later", startedAt: 200 }),
        session({ taskRunId: "earlier", startedAt: 100 }),
      ],
      expectedTaskRunIds: ["earlier", "later"],
    },
  ])("$name", ({ sessions, expectedTaskRunIds }) => {
    const record = Object.fromEntries(sessions.map((s) => [s.taskRunId, s]));
    expect(listWorkingLocalSessions(record).map((s) => s.taskRunId)).toEqual(
      expectedTaskRunIds,
    );
  });

  it.each([
    { taskTitle: "", expected: "Untitled task" },
    { taskTitle: "   ", expected: "Untitled task" },
    { taskTitle: " Fix login ", expected: "Fix login" },
  ])(
    "presents the title $taskTitle as $expected",
    ({ taskTitle, expected }) => {
      const record = { a: session({ taskRunId: "a", taskTitle }) };
      expect(listWorkingLocalSessions(record)[0]?.taskTitle).toBe(expected);
    },
  );

  it("changes the signature only when membership or a title changes", () => {
    const base = { a: session({ taskRunId: "a" }) };
    const sameWorkDifferentObject = { a: session({ taskRunId: "a" }) };
    const renamed = { a: session({ taskRunId: "a", taskTitle: "Renamed" }) };
    const drained = {
      a: session({ taskRunId: "a", isPromptPending: false }),
    };

    expect(computeWorkingLocalSessionsSignature(base)).toBe(
      computeWorkingLocalSessionsSignature(sameWorkDifferentObject),
    );
    expect(computeWorkingLocalSessionsSignature(base)).not.toBe(
      computeWorkingLocalSessionsSignature(renamed),
    );
    expect(computeWorkingLocalSessionsSignature(base)).not.toBe(
      computeWorkingLocalSessionsSignature(drained),
    );
  });
});
