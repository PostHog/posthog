import { beforeEach, describe, expect, it } from "vitest";
import { useSideQuestionStore } from "./sideQuestionStore";

describe("sideQuestionStore stale-answer guard", () => {
  beforeEach(() => {
    useSideQuestionStore.setState({ byTaskId: {} });
  });

  it("does not repopulate a dismissed entry with a late answer", () => {
    const { ask, dismiss, resolve } = useSideQuestionStore.getState();

    const id = ask("task-1", "run-1", "what changed?");
    dismiss("task-1");
    resolve("task-1", "run-1", id, "the late answer");

    expect(useSideQuestionStore.getState().byTaskId["task-1"]).toBeUndefined();
  });

  it("does not let a stale answer clobber a re-asked question", () => {
    const { ask, resolve } = useSideQuestionStore.getState();

    const firstId = ask("task-1", "run-1", "first question?");
    const secondId = ask("task-1", "run-1", "second question?");
    resolve("task-1", "run-1", firstId, "answer to the first question");

    const entry = useSideQuestionStore.getState().byTaskId["task-1"];
    expect(entry?.id).toBe(secondId);
    expect(entry?.status).toBe("pending");
  });

  it("does not settle an answer against a run the task has since moved on from", () => {
    const { ask, resolve } = useSideQuestionStore.getState();

    const id = ask("task-1", "run-1", "what changed?");
    resolve("task-1", "run-2", id, "answer from the old run");

    const entry = useSideQuestionStore.getState().byTaskId["task-1"];
    expect(entry?.status).toBe("pending");
  });
});
