import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ArchiveClient } from "./identifiers";
import { UnarchiveService } from "./unarchiveService";

const TASK_ID = "task-1";

function makeClient(): ArchiveClient {
  return {
    unarchive: vi.fn().mockResolvedValue(undefined),
    delete: vi.fn().mockResolvedValue(undefined),
    showArchivedTaskContextMenu: vi.fn().mockResolvedValue({ action: null }),
  };
}

describe("UnarchiveService.unarchiveTask", () => {
  let client: ArchiveClient;
  let service: UnarchiveService;

  beforeEach(() => {
    client = makeClient();
    service = new UnarchiveService(client);
  });

  it("returns ok and calls the client on success", async () => {
    const result = await service.unarchiveTask(TASK_ID);

    expect(result).toEqual({ ok: true });
    expect(client.unarchive).toHaveBeenCalledWith({
      taskId: TASK_ID,
      recreateBranch: undefined,
    });
  });

  it("forwards recreateBranch to the client", async () => {
    await service.unarchiveTask(TASK_ID, { recreateBranch: true });

    expect(client.unarchive).toHaveBeenCalledWith({
      taskId: TASK_ID,
      recreateBranch: true,
    });
  });

  it("classifies a missing branch as branch-not-found", async () => {
    client.unarchive = vi
      .fn()
      .mockRejectedValue(new Error("Branch 'feature/x' does not exist"));

    const result = await service.unarchiveTask(TASK_ID);

    expect(result).toEqual({
      ok: false,
      kind: "branch-not-found",
      branchName: "feature/x",
    });
  });

  it("classifies any other failure as other", async () => {
    client.unarchive = vi.fn().mockRejectedValue(new Error("boom"));

    const result = await service.unarchiveTask(TASK_ID);

    expect(result).toEqual({ ok: false, kind: "other", message: "boom" });
  });
});

describe("UnarchiveService.deleteArchivedTask", () => {
  it("returns ok on success", async () => {
    const client = makeClient();
    const service = new UnarchiveService(client);

    const result = await service.deleteArchivedTask(TASK_ID);

    expect(result).toEqual({ ok: true });
    expect(client.delete).toHaveBeenCalledWith({ taskId: TASK_ID });
  });

  it("returns the error message on failure", async () => {
    const client = makeClient();
    client.delete = vi.fn().mockRejectedValue(new Error("nope"));
    const service = new UnarchiveService(client);

    const result = await service.deleteArchivedTask(TASK_ID);

    expect(result).toEqual({ ok: false, message: "nope" });
  });
});

describe("UnarchiveService.requestContextMenuAction", () => {
  it("maps the chosen menu action type", async () => {
    const client = makeClient();
    client.showArchivedTaskContextMenu = vi
      .fn()
      .mockResolvedValue({ action: { type: "restore" } });
    const service = new UnarchiveService(client);

    const result = await service.requestContextMenuAction("Title");

    expect(result).toEqual({ action: "restore" });
  });

  it("returns a null action when the menu is dismissed", async () => {
    const client = makeClient();
    const service = new UnarchiveService(client);

    const result = await service.requestContextMenuAction("Title");

    expect(result).toEqual({ action: null });
  });

  it("returns an error when the menu call throws", async () => {
    const client = makeClient();
    client.showArchivedTaskContextMenu = vi
      .fn()
      .mockRejectedValue(new Error("menu broke"));
    const service = new UnarchiveService(client);

    const result = await service.requestContextMenuAction("Title");

    expect(result).toEqual({ error: "menu broke" });
  });
});
