import { describe, expect, it } from "vitest";
import { canvasChatTaskId } from "./canvasChatTask";

describe("canvasChatTaskId", () => {
  const versions = [
    { taskId: "task-b", createdByUuid: "user-b" },
    { taskId: "task-a", createdByUuid: "user-a" },
    { taskId: "task-a-old", createdByUuid: "user-a" },
  ];

  it.each([
    {
      name: "shows this person's newest run instead of the other person's live run",
      generationTaskId: "task-b",
      generationTaskCreatorUuid: "user-b",
      currentUserUuid: "user-a",
      expected: "task-a",
    },
    {
      name: "shows the live run when this person started it",
      generationTaskId: "task-a-live",
      generationTaskCreatorUuid: "user-a",
      currentUserUuid: "user-a",
      expected: "task-a-live",
    },
    {
      name: "shows nothing to a person with no run on the canvas",
      generationTaskId: "task-b",
      generationTaskCreatorUuid: "user-b",
      currentUserUuid: "user-c",
      expected: null,
    },
  ])("$name", ({ expected, ...args }) => {
    expect(canvasChatTaskId({ startedTaskId: null, versions, ...args })).toBe(
      expected,
    );
  });

  it("prefers the run just started here while the record catches up", () => {
    expect(
      canvasChatTaskId({
        startedTaskId: "task-new",
        generationTaskId: "task-b",
        generationTaskCreatorUuid: "user-b",
        versions,
        currentUserUuid: "user-a",
      }),
    ).toBe("task-new");
  });
});
