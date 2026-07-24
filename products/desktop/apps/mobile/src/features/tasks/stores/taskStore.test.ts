import { describe, expect, it } from "vitest";
import type { Task } from "../types";
import { filterAndSortTasks } from "./taskStore";

function makeTask(overrides: Partial<Task>): Task {
  return {
    id: "task-1",
    task_number: 1,
    slug: "task-1",
    title: "A real task",
    description: "Do the thing",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    origin_product: "tasks",
    ...overrides,
  };
}

describe("filterAndSortTasks", () => {
  it.each([
    { name: "empty title and description", title: "", description: "" },
    { name: "whitespace-only fields", title: "   ", description: "\n\t" },
  ])(
    "hides warm-sandbox placeholder tasks ($name)",
    ({ title, description }) => {
      const placeholder = makeTask({ id: "warm", title, description });
      const real = makeTask({ id: "real" });

      const result = filterAndSortTasks(
        [placeholder, real],
        "updated",
        false,
        "",
      );

      expect(result.map((t) => t.id)).toEqual(["real"]);
    },
  );

  it.each([
    {
      name: "description only (title not landed yet)",
      title: "",
      description: "Fix login",
    },
    { name: "title only", title: "Fix login", description: "" },
  ])("keeps a real task with $name", ({ title, description }) => {
    const task = makeTask({ id: "real", title, description });

    const result = filterAndSortTasks([task], "updated", false, "");

    expect(result.map((t) => t.id)).toEqual(["real"]);
  });
});
