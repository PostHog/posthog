import { Alert } from "react-native";
import { describe, expect, it, vi } from "vitest";
import type { Task, TaskRunStatus } from "../types";
import { confirmArchiveRunningTask, isTaskRunning } from "./archiveGuard";

function makeTask(status?: TaskRunStatus): Task {
  return {
    id: "task-1",
    task_number: 1,
    slug: "task-1",
    title: "Test task",
    description: "",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    origin_product: "code",
    latest_run: status
      ? {
          id: "run-1",
          task: "task-1",
          team: 1,
          branch: null,
          stage: null,
          environment: "cloud",
          status,
          log_url: "",
          error_message: null,
          output: null,
          state: {},
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
          completed_at: null,
        }
      : undefined,
  };
}

describe("isTaskRunning", () => {
  it("treats a task with no run as not running", () => {
    expect(isTaskRunning(makeTask())).toBe(false);
  });

  it.each(["not_started", "queued", "started", "in_progress"] as const)(
    "treats %s as running",
    (status) => {
      expect(isTaskRunning(makeTask(status))).toBe(true);
    },
  );

  it.each(["completed", "failed", "cancelled"] as const)(
    "treats %s as not running",
    (status) => {
      expect(isTaskRunning(makeTask(status))).toBe(false);
    },
  );
});

describe("confirmArchiveRunningTask", () => {
  it("archives only when the user confirms", () => {
    const onConfirm = vi.fn();
    confirmArchiveRunningTask("My task", onConfirm);

    expect(Alert.alert).toHaveBeenCalledTimes(1);
    const [title, message, buttons] = vi.mocked(Alert.alert).mock.calls[0];
    expect(title).toBe("Archive running task?");
    expect(message).toContain("My task");
    expect(message).toContain("stop the agent");

    const cancelButton = buttons?.find((b) => b.text === "Cancel");
    const archiveButton = buttons?.find((b) => b.text === "Archive");

    cancelButton?.onPress?.();
    expect(onConfirm).not.toHaveBeenCalled();

    archiveButton?.onPress?.();
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});
