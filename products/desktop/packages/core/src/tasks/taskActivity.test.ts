import type { Task } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import { filterAndSortTasks, taskActivityTimestamp } from "./taskActivity";

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: "task-1",
    task_number: 1,
    slug: "task-1",
    title: "A real task",
    description: "Do the thing",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    origin_product: "tasks",
    ...overrides,
  };
}

describe("taskActivityTimestamp", () => {
  it("uses creation time in created mode", () => {
    const task = makeTask({
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-03T00:00:00Z",
    });

    expect(taskActivityTimestamp(task, "created")).toBe(
      new Date("2026-01-01T00:00:00Z").getTime(),
    );
  });

  it("uses the latest task or run update in updated mode", () => {
    const task = makeTask({
      updated_at: "2026-01-02T00:00:00Z",
      latest_run: {
        id: "run-1",
        task: "task-1",
        team: 1,
        branch: null,
        status: "completed",
        log_url: "",
        error_message: null,
        output: null,
        state: {},
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-04T00:00:00Z",
        completed_at: "2026-01-04T00:00:00Z",
      },
    });

    expect(taskActivityTimestamp(task, "updated")).toBe(
      new Date("2026-01-04T00:00:00Z").getTime(),
    );
  });
});

describe("filterAndSortTasks", () => {
  it.each([
    { title: "", description: "" },
    { title: "   ", description: "\n\t" },
  ])("hides contentless placeholder tasks", ({ title, description }) => {
    const placeholder = makeTask({ id: "placeholder", title, description });
    const realTask = makeTask({ id: "real" });

    expect(
      filterAndSortTasks([placeholder, realTask], "updated", false, "").map(
        (task) => task.id,
      ),
    ).toEqual(["real"]);
  });

  it("selects internal or external tasks", () => {
    const externalTask = makeTask({ id: "external", internal: false });
    const internalTask = makeTask({ id: "internal", internal: true });

    expect(
      filterAndSortTasks(
        [externalTask, internalTask],
        "updated",
        false,
        "",
      ).map((task) => task.id),
    ).toEqual(["external"]);
    expect(
      filterAndSortTasks([externalTask, internalTask], "updated", true, "").map(
        (task) => task.id,
      ),
    ).toEqual(["internal"]);
  });

  it.each([
    ["title", { title: "Fix Login" }],
    ["slug", { slug: "fix-login" }],
    ["description", { description: "Fix Login" }],
  ] as const)("matches a case-insensitive %s filter", (_field, overrides) => {
    const matchingTask = makeTask({ id: "matching", ...overrides });
    const otherTask = makeTask({ id: "other", title: "Unrelated" });

    expect(
      filterAndSortTasks(
        [otherTask, matchingTask],
        "updated",
        false,
        "LOGIN",
      ).map((task) => task.id),
    ).toEqual(["matching"]);
  });

  it("sorts by the selected activity timestamp without mutating input", () => {
    const olderCreated = makeTask({
      id: "older-created",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-04T00:00:00Z",
    });
    const newerCreated = makeTask({
      id: "newer-created",
      created_at: "2026-01-02T00:00:00Z",
      updated_at: "2026-01-03T00:00:00Z",
    });
    const tasks = [olderCreated, newerCreated];

    expect(
      filterAndSortTasks(tasks, "created", false, "").map((task) => task.id),
    ).toEqual(["newer-created", "older-created"]);
    expect(
      filterAndSortTasks(tasks, "updated", false, "").map((task) => task.id),
    ).toEqual(["older-created", "newer-created"]);
    expect(tasks.map((task) => task.id)).toEqual([
      "older-created",
      "newer-created",
    ]);
  });
});
