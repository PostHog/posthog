import type { Task, TaskRunStatus } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import type { TaskSession } from "../stores/taskSessionStore";
import {
  collectAwaitingInputTaskIds,
  isTaskAwaitingUserInput,
} from "./awaitingInput";

function session(overrides: Partial<TaskSession>): TaskSession {
  return {
    taskRunId: "run",
    taskId: "task",
    events: [],
    status: "connected",
    isPromptPending: false,
    ...overrides,
  };
}

function task(
  id: string,
  run?: { awaiting?: boolean; status?: TaskRunStatus },
): Task {
  return {
    id,
    latest_run: run
      ? {
          status: run.status ?? "in_progress",
          state: run.awaiting ? { awaiting_user_input: true } : {},
        }
      : null,
  } as Task;
}

describe("isTaskAwaitingUserInput", () => {
  it.each([
    {
      name: "a live session that says so",
      task: task("t", { awaiting: false }),
      session: session({ isAwaitingUserInput: true }),
      expected: true,
    },
    {
      name: "a live session wins over a stale server marker",
      task: task("t", { awaiting: true }),
      session: session({ isAwaitingUserInput: false }),
      expected: false,
    },
    {
      name: "a session whose run has terminated",
      task: task("t", { awaiting: true }),
      session: session({
        isAwaitingUserInput: true,
        terminalStatus: "stopped",
      }),
      expected: false,
    },
    {
      name: "the server marker with no session",
      task: task("t", { awaiting: true }),
      session: undefined,
      expected: true,
    },
    {
      name: "the server marker on a run that has since completed",
      task: task("t", { awaiting: true, status: "completed" }),
      session: undefined,
      expected: false,
    },
    {
      name: "a task with no marker and no session",
      task: task("t", { awaiting: false }),
      session: undefined,
      expected: false,
    },
    {
      name: "a task that has never run",
      task: task("t"),
      session: undefined,
      expected: false,
    },
    {
      name: "an errored session, which falls through to the server marker",
      task: task("t", { awaiting: true }),
      session: session({ status: "error", isAwaitingUserInput: false }),
      expected: true,
    },
    {
      name: "a disconnected session, which falls through to the server marker",
      task: task("t", { awaiting: true }),
      session: session({ status: "disconnected", isAwaitingUserInput: false }),
      expected: true,
    },
    {
      name: "an errored session on a task the server does not flag",
      task: task("t", { awaiting: false }),
      session: session({ status: "error", isAwaitingUserInput: true }),
      expected: false,
    },
    {
      name: "a connecting session, which is still live",
      task: task("t", { awaiting: true }),
      session: session({ status: "connecting", isAwaitingUserInput: false }),
      expected: false,
    },
  ])("is $expected for $name", ({ task: t, session: s, expected }) => {
    expect(isTaskAwaitingUserInput(t, s)).toBe(expected);
  });
});

describe("collectAwaitingInputTaskIds", () => {
  it("collects the task id of every session blocked on the user", () => {
    const ids = collectAwaitingInputTaskIds({
      a: session({ taskRunId: "a", taskId: "t-a", isAwaitingUserInput: true }),
      b: session({ taskRunId: "b", taskId: "t-b" }),
      c: session({ taskRunId: "c", taskId: "t-c", isAwaitingUserInput: true }),
    });

    expect(Array.from(ids).sort()).toEqual(["t-a", "t-c"]);
  });

  it("ignores a session whose run has already terminated", () => {
    const ids = collectAwaitingInputTaskIds({
      a: session({
        taskId: "t-a",
        isAwaitingUserInput: true,
        terminalStatus: "stopped",
      }),
    });

    expect(ids.size).toBe(0);
  });

  it("is empty when nothing is connected", () => {
    expect(collectAwaitingInputTaskIds({}).size).toBe(0);
  });

  it("collects tasks the server flags without a session in this app", () => {
    const ids = collectAwaitingInputTaskIds({}, [
      task("t-a", { awaiting: true }),
      task("t-b", { awaiting: false }),
    ]);

    expect(Array.from(ids)).toEqual(["t-a"]);
  });

  it("lets a live session override the server marker for the same task", () => {
    const ids = collectAwaitingInputTaskIds(
      { a: session({ taskId: "t-a", isAwaitingUserInput: false }) },
      [task("t-a", { awaiting: true })],
    );

    expect(ids.size).toBe(0);
  });

  it("keeps a blocked session for a task the list does not carry", () => {
    const ids = collectAwaitingInputTaskIds(
      { a: session({ taskId: "t-hidden", isAwaitingUserInput: true }) },
      [task("t-a", { awaiting: false })],
    );

    expect(Array.from(ids)).toEqual(["t-hidden"]);
  });

  it("falls back to the server marker when the session's stream died", () => {
    const ids = collectAwaitingInputTaskIds(
      {
        a: session({
          taskId: "t-a",
          status: "error",
          isAwaitingUserInput: false,
        }),
      },
      [task("t-a", { awaiting: true })],
    );

    expect(Array.from(ids)).toEqual(["t-a"]);
  });

  it("lets the newest run's session decide when a task has several", () => {
    const ids = collectAwaitingInputTaskIds(
      {
        old: session({
          taskRunId: "old",
          taskId: "t-a",
          isAwaitingUserInput: true,
        }),
        new: session({
          taskRunId: "new",
          taskId: "t-a",
          isAwaitingUserInput: false,
        }),
      },
      [task("t-a", { awaiting: true })],
    );

    expect(ids.size).toBe(0);
  });
});
