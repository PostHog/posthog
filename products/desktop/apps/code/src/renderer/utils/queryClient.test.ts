import type { Task } from "@posthog/shared/domain-types";
import { focusManager } from "@tanstack/react-query";
import { beforeEach, describe, expect, it } from "vitest";
import { getCachedTask, queryClient } from "./queryClient";

const createTask = (overrides: Partial<Task> = {}): Task => ({
  id: "task-1",
  task_number: 1,
  slug: "task-1",
  title: "Test task",
  description: "",
  origin_product: "user_created",
  repository: null,
  created_at: "2026-04-15T00:00:00Z",
  updated_at: "2026-04-15T00:00:00Z",
  ...overrides,
});

describe("getCachedTask", () => {
  beforeEach(() => {
    queryClient.clear();
  });

  it("returns matching task from cache", () => {
    const tasks = [createTask({ id: "task-1" }), createTask({ id: "task-2" })];
    queryClient.setQueryData(["tasks", "list"], tasks);

    expect(getCachedTask("task-1")?.id).toBe("task-1");
    expect(getCachedTask("task-2")?.id).toBe("task-2");
  });

  it("returns undefined when task is not in cache", () => {
    queryClient.setQueryData(["tasks", "list"], [createTask({ id: "task-1" })]);

    expect(getCachedTask("nonexistent")).toBeUndefined();
  });

  it("returns undefined when no task queries exist", () => {
    expect(getCachedTask("task-1")).toBeUndefined();
  });

  it("searches across multiple task list queries", () => {
    queryClient.setQueryData(
      ["tasks", "list", { folder: "a" }],
      [createTask({ id: "task-a" })],
    );
    queryClient.setQueryData(
      ["tasks", "list", { folder: "b" }],
      [createTask({ id: "task-b" })],
    );

    expect(getCachedTask("task-a")?.id).toBe("task-a");
    expect(getCachedTask("task-b")?.id).toBe("task-b");
  });

  it("preserves title_manually_set flag", () => {
    queryClient.setQueryData(
      ["tasks", "list"],
      [createTask({ id: "task-1", title_manually_set: true })],
    );

    expect(getCachedTask("task-1")?.title_manually_set).toBe(true);
  });
});

describe("focusManager", () => {
  it("flips focus state on window focus/blur events", () => {
    window.dispatchEvent(new Event("blur"));
    expect(focusManager.isFocused()).toBe(false);

    window.dispatchEvent(new Event("focus"));
    expect(focusManager.isFocused()).toBe(true);
  });
});
