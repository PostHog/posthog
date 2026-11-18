import type { Task } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  isSandboxPromptTask,
  selectAvailableTasks,
  workspaceIdSet,
} from "./eligibility";

function makeTask(id: string, title = id): Task {
  return {
    id,
    task_number: 1,
    slug: id,
    title,
    description: "",
    created_at: "",
    updated_at: "",
    origin_product: "code",
  } as Task;
}

describe("selectAvailableTasks", () => {
  it("keeps tasks that are unassigned, unarchived, and have a workspace", () => {
    const tasks = [makeTask("a"), makeTask("b"), makeTask("c"), makeTask("d")];
    const result = selectAvailableTasks(tasks, {
      assignedIds: new Set(["a"]),
      archivedIds: new Set(["b"]),
      workspaceIds: workspaceIdSet({ a: {}, b: {}, c: {} }),
    });
    expect(result.map((t) => t.id)).toEqual(["c"]);
  });

  it("excludes internal sandbox prompt tasks", () => {
    const sandboxPrompt = makeTask(
      "sandbox-task",
      "[sandbox_prompt:repo_selection] Choose a repository",
    );
    const visibleTask = makeTask("visible-task", "Fix the login flow");

    const result = selectAvailableTasks([sandboxPrompt, visibleTask], {
      assignedIds: new Set(),
      archivedIds: new Set(),
      workspaceIds: workspaceIdSet({
        "sandbox-task": {},
        "visible-task": {},
      }),
    });

    expect(result.map((task) => task.id)).toEqual(["visible-task"]);
    expect(isSandboxPromptTask(sandboxPrompt)).toBe(true);
    expect(isSandboxPromptTask(visibleTask)).toBe(false);
  });
});
