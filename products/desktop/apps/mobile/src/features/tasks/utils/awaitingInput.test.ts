import { describe, expect, it } from "vitest";
import type { TaskSession } from "../stores/taskSessionStore";
import { collectAwaitingInputTaskIds } from "./awaitingInput";

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
});
