import { describe, expect, it } from "vitest";
import { createBaseSession } from "./sessionFactory";

describe("createBaseSession", () => {
  it("builds a connecting session with empty collections", () => {
    const session = createBaseSession("run-1", "task-1", "My Task");

    expect(session).toMatchObject({
      taskRunId: "run-1",
      taskId: "task-1",
      taskTitle: "My Task",
      channel: "agent-event:run-1",
      status: "connecting",
      isPromptPending: false,
      isCompacting: false,
      promptStartedAt: null,
      pausedDurationMs: 0,
    });
    expect(session.events).toEqual([]);
    expect(session.messageQueue).toEqual([]);
    expect(session.optimisticItems).toEqual([]);
    expect(session.pendingPermissions).toBeInstanceOf(Map);
    expect(session.pendingPermissions.size).toBe(0);
    expect(typeof session.startedAt).toBe("number");
  });

  it("derives the channel name from the task run id", () => {
    expect(createBaseSession("abc", "t", "title").channel).toBe(
      "agent-event:abc",
    );
  });

  it("returns independent collection instances per call", () => {
    const a = createBaseSession("run-a", "task-a", "A");
    const b = createBaseSession("run-b", "task-b", "B");
    a.events.push({ message: { method: "x" } } as never);
    expect(b.events).toEqual([]);
    expect(a.pendingPermissions).not.toBe(b.pendingPermissions);
  });
});
