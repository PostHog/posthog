import { beforeEach, describe, expect, it, vi } from "vitest";
import type { UseUnarchiveTask } from "./useUnarchiveTask";

const toastSuccess = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());

vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { success: toastSuccess, error: toastError },
}));
vi.mock("@posthog/ui/shell/logger", () => ({
  logger: { scope: () => ({ error: vi.fn(), info: vi.fn(), warn: vi.fn() }) },
}));

import { undoArchive } from "./undoArchive";

type Restore = UseUnarchiveTask["restore"];

describe("undoArchive", () => {
  beforeEach(() => {
    toastSuccess.mockClear();
    toastError.mockClear();
  });

  it("restores on the first attempt and confirms with a toast", async () => {
    const restore = vi
      .fn()
      .mockResolvedValue({ kind: "restored", navigateToTaskId: "task-1" });

    await undoArchive("task-1", restore as unknown as Restore);

    expect(restore).toHaveBeenCalledTimes(1);
    expect(restore).toHaveBeenCalledWith("task-1", true);
    expect(toastSuccess).toHaveBeenCalledWith("Task archive undone");
    expect(toastError).not.toHaveBeenCalled();
  });

  it("retries with branch recreation when the branch is missing", async () => {
    const restore = vi
      .fn()
      .mockResolvedValueOnce({
        kind: "branch-not-found",
        taskId: "task-1",
        branchName: "feat/x",
      })
      .mockResolvedValueOnce({ kind: "restored", navigateToTaskId: "task-1" });

    await undoArchive("task-1", restore as unknown as Restore);

    expect(restore).toHaveBeenNthCalledWith(1, "task-1", true);
    expect(restore).toHaveBeenNthCalledWith(2, "task-1", true, {
      recreateBranch: true,
    });
    expect(toastSuccess).toHaveBeenCalledWith("Task archive undone");
    expect(toastError).not.toHaveBeenCalled();
  });

  it("shows an error toast when the branch is still missing after retry", async () => {
    const restore = vi.fn().mockResolvedValue({
      kind: "branch-not-found",
      taskId: "task-1",
      branchName: "feat/x",
    });

    await undoArchive("task-1", restore as unknown as Restore);

    expect(restore).toHaveBeenCalledTimes(2);
    expect(toastError).toHaveBeenCalledWith(
      "Failed to restore task: branch 'feat/x' not found",
    );
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it("surfaces the error message when restore reports an error", async () => {
    const restore = vi
      .fn()
      .mockResolvedValue({ kind: "error", message: "server boom" });

    await undoArchive("task-1", restore as unknown as Restore);

    expect(toastError).toHaveBeenCalledWith(
      "Failed to restore task: server boom",
    );
  });

  it("shows a generic error toast when restore throws", async () => {
    const restore = vi.fn().mockRejectedValue(new Error("network down"));

    await undoArchive("task-1", restore as unknown as Restore);

    expect(toastError).toHaveBeenCalledWith("Failed to restore task");
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it("ignores a repeated undo while the first is still in flight", async () => {
    let resolveRestore: (value: unknown) => void = () => {};
    const restore = vi.fn().mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveRestore = resolve;
        }),
    );

    const first = undoArchive("task-1", restore as unknown as Restore);
    const second = undoArchive("task-1", restore as unknown as Restore);
    resolveRestore({ kind: "restored", navigateToTaskId: "task-1" });
    await Promise.all([first, second]);

    expect(restore).toHaveBeenCalledTimes(1);
    expect(toastSuccess).toHaveBeenCalledTimes(1);
  });
});
