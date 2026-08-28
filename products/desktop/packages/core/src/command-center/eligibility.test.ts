import type { Task } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import { selectAvailableTasks, workspaceIdSet } from "./eligibility";

function makeTask(id: string): Task {
  return {
    id,
    task_number: 1,
    slug: id,
    title: id,
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
});
