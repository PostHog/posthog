import { beforeEach, describe, expect, it, vi } from "vitest";
import { ArchivedTasksController } from "./archivedTasksController";
import type { UnarchiveService } from "./unarchiveService";

const TASK_ID = "task-1";

function makeUnarchive(): UnarchiveService {
  return {
    unarchiveTask: vi.fn().mockResolvedValue({ ok: true }),
    deleteArchivedTask: vi.fn().mockResolvedValue({ ok: true }),
    requestContextMenuAction: vi.fn().mockResolvedValue({ action: null }),
  } as unknown as UnarchiveService;
}

describe("ArchivedTasksController.restore", () => {
  let unarchive: UnarchiveService;
  let controller: ArchivedTasksController;

  beforeEach(() => {
    unarchive = makeUnarchive();
    controller = new ArchivedTasksController(unarchive);
  });

  it("returns the task id to navigate to when a task exists", async () => {
    const outcome = await controller.restore(TASK_ID, true);

    expect(outcome).toEqual({ kind: "restored", navigateToTaskId: TASK_ID });
  });

  it("returns a null navigation target when no task exists", async () => {
    const outcome = await controller.restore(TASK_ID, false);

    expect(outcome).toEqual({ kind: "restored", navigateToTaskId: null });
  });

  it("forwards recreateBranch to the service", async () => {
    await controller.restore(TASK_ID, true, { recreateBranch: true });

    expect(unarchive.unarchiveTask).toHaveBeenCalledWith(TASK_ID, {
      recreateBranch: true,
    });
  });

  it("surfaces a branch-not-found outcome", async () => {
    unarchive.unarchiveTask = vi.fn().mockResolvedValue({
      ok: false,
      kind: "branch-not-found",
      branchName: "feature/x",
    });

    const outcome = await controller.restore(TASK_ID, true);

    expect(outcome).toEqual({
      kind: "branch-not-found",
      taskId: TASK_ID,
      branchName: "feature/x",
    });
  });

  it("surfaces an error outcome on other failures", async () => {
    unarchive.unarchiveTask = vi
      .fn()
      .mockResolvedValue({ ok: false, kind: "other", message: "boom" });

    const outcome = await controller.restore(TASK_ID, true);

    expect(outcome).toEqual({ kind: "error", message: "boom" });
  });
});

describe("ArchivedTasksController.remove", () => {
  it("returns a deleted outcome on success", async () => {
    const controller = new ArchivedTasksController(makeUnarchive());

    const outcome = await controller.remove(TASK_ID);

    expect(outcome).toEqual({ kind: "deleted" });
  });

  it("returns an error outcome on failure", async () => {
    const unarchive = makeUnarchive();
    unarchive.deleteArchivedTask = vi
      .fn()
      .mockResolvedValue({ ok: false, message: "nope" });
    const controller = new ArchivedTasksController(unarchive);

    const outcome = await controller.remove(TASK_ID);

    expect(outcome).toEqual({ kind: "error", message: "nope" });
  });
});

describe("ArchivedTasksController.runContextMenuAction", () => {
  it("returns a menu-error when the menu call fails", async () => {
    const unarchive = makeUnarchive();
    unarchive.requestContextMenuAction = vi
      .fn()
      .mockResolvedValue({ error: "menu broke" });
    const controller = new ArchivedTasksController(unarchive);

    const outcome = await controller.runContextMenuAction(
      TASK_ID,
      "Title",
      true,
    );

    expect(outcome).toEqual({ kind: "menu-error", message: "menu broke" });
  });

  it("dispatches restore and wraps the outcome", async () => {
    const unarchive = makeUnarchive();
    unarchive.requestContextMenuAction = vi
      .fn()
      .mockResolvedValue({ action: "restore" });
    const controller = new ArchivedTasksController(unarchive);

    const outcome = await controller.runContextMenuAction(
      TASK_ID,
      "Title",
      true,
    );

    expect(outcome).toEqual({
      kind: "restore",
      outcome: { kind: "restored", navigateToTaskId: TASK_ID },
    });
  });

  it("dispatches delete and wraps the outcome", async () => {
    const unarchive = makeUnarchive();
    unarchive.requestContextMenuAction = vi
      .fn()
      .mockResolvedValue({ action: "delete" });
    const controller = new ArchivedTasksController(unarchive);

    const outcome = await controller.runContextMenuAction(
      TASK_ID,
      "Title",
      true,
    );

    expect(outcome).toEqual({ kind: "delete", outcome: { kind: "deleted" } });
  });

  it("returns a noop when the menu is dismissed", async () => {
    const controller = new ArchivedTasksController(makeUnarchive());

    const outcome = await controller.runContextMenuAction(
      TASK_ID,
      "Title",
      true,
    );

    expect(outcome).toEqual({ kind: "noop" });
  });
});
