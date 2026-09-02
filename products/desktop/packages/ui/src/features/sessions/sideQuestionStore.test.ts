import { beforeEach, describe, expect, it } from "vitest";
import { useSideQuestionStore } from "./sideQuestionStore";

/** `ask` returns null when one is already pending; these cases expect it to take. */
function askId(taskId: string, taskRunId: string, question: string): string {
  const id = useSideQuestionStore.getState().ask(taskId, taskRunId, question);
  if (!id) throw new Error(`ask unexpectedly refused: ${question}`);
  return id;
}

describe("sideQuestionStore", () => {
  beforeEach(() => {
    useSideQuestionStore.setState({ byTaskId: {} });
  });

  it("does not repopulate a dismissed entry with a late answer", () => {
    const { dismiss, resolve } = useSideQuestionStore.getState();

    const id = askId("task-1", "run-1", "what changed?");
    dismiss("task-1");
    resolve("task-1", "run-1", id, "the late answer");

    expect(useSideQuestionStore.getState().byTaskId["task-1"]).toBeUndefined();
  });

  it("refuses a second question while the first is still pending", () => {
    const { ask } = useSideQuestionStore.getState();

    const firstId = askId("task-1", "run-1", "first question?");
    expect(ask("task-1", "run-1", "second question?")).toBeNull();

    const entry = useSideQuestionStore.getState().byTaskId["task-1"];
    expect(entry?.id).toBe(firstId);
    expect(entry?.question).toBe("first question?");
  });

  it.each([
    [
      "answered",
      (id: string) =>
        useSideQuestionStore
          .getState()
          .resolve("task-1", "run-1", id, "the answer"),
    ],
    [
      "failed",
      (id: string) =>
        useSideQuestionStore.getState().fail("task-1", "run-1", id, "it broke"),
    ],
  ])("allows a new question once the previous one has %s", (_label, settle) => {
    const firstId = askId("task-1", "run-1", "first question?");
    settle(firstId);

    expect(
      useSideQuestionStore.getState().ask("task-1", "run-1", "second?"),
    ).not.toBeNull();
  });

  it("does not let a stale answer clobber a question asked after a dismiss", () => {
    const { dismiss, resolve } = useSideQuestionStore.getState();

    const firstId = askId("task-1", "run-1", "first question?");
    dismiss("task-1");
    const secondId = askId("task-1", "run-1", "second question?");
    resolve("task-1", "run-1", firstId, "answer to the first");

    const entry = useSideQuestionStore.getState().byTaskId["task-1"];
    expect(entry?.id).toBe(secondId);
    expect(entry?.status).toBe("pending");
  });

  it("does not settle an answer against a run the task has since moved on from", () => {
    const { resolve } = useSideQuestionStore.getState();

    const id = askId("task-1", "run-1", "what changed?");
    resolve("task-1", "run-2", id, "answer from the old run");

    const entry = useSideQuestionStore.getState().byTaskId["task-1"];
    expect(entry?.status).toBe("pending");
  });
});
