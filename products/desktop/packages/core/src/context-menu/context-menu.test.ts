import type {
  ContextMenuAction,
  ContextMenuItem,
  IContextMenu,
  ShowContextMenuOptions,
} from "@posthog/platform/context-menu";
import type { ConfirmOptions, IDialog } from "@posthog/platform/dialog";
import { describe, expect, it } from "vitest";
import { ContextMenuService } from "./context-menu";
import type { IContextMenuExternalApps } from "./identifiers";
import type { TaskContextMenuInput } from "./schemas";

class FakeContextMenu implements IContextMenu {
  lastItems: ContextMenuItem[] = [];
  lastOptions?: ShowContextMenuOptions;
  private shownResolve!: () => void;
  readonly shown = new Promise<void>((resolve) => {
    this.shownResolve = resolve;
  });

  show(items: ContextMenuItem[], options?: ShowContextMenuOptions): void {
    this.lastItems = items;
    this.lastOptions = options;
    this.shownResolve();
  }
}

const noExternalApps: IContextMenuExternalApps = {
  getDetectedApps: async () => [],
  getLastUsed: async () => ({}),
};

function dialogReturning(response: number): IDialog {
  return {
    confirm: async (_options: ConfirmOptions) => response,
  } as IDialog;
}

function labels(items: ContextMenuItem[]): string[] {
  return items
    .filter((i): i is ContextMenuAction => !("separator" in i))
    .map((i) => i.label);
}

function findItem(items: ContextMenuItem[], label: string): ContextMenuAction {
  const item = items.find(
    (i): i is ContextMenuAction => !("separator" in i) && i.label === label,
  );
  if (!item) throw new Error(`menu item "${label}" not found`);
  return item;
}

function makeService(menu: IContextMenu, dialog: IDialog = dialogReturning(1)) {
  return new ContextMenuService(noExternalApps, dialog, menu);
}

const baseTask: TaskContextMenuInput = {
  taskTitle: "Task",
  isPinned: false,
  isSuspended: false,
  isInCommandCenter: false,
  hasEmptyCommandCenterCell: true,
};

describe("ContextMenuService.showTaskContextMenu", () => {
  it("shows Pin/Unpin based on isPinned", async () => {
    const menu = new FakeContextMenu();
    const pinned = makeService(menu).showTaskContextMenu({
      ...baseTask,
      isPinned: true,
    });
    await menu.shown;
    expect(labels(menu.lastItems)).toContain("Unpin");
    expect(labels(menu.lastItems)).not.toContain("Pin");
    findItem(menu.lastItems, "Unpin").click();
    expect(await pinned).toEqual({ action: { type: "pin" } });
  });

  it("only offers Suspend when the task has a worktree", async () => {
    const withWt = new FakeContextMenu();
    makeService(withWt).showTaskContextMenu({
      ...baseTask,
      worktreePath: "/wt",
    });
    await withWt.shown;
    expect(labels(withWt.lastItems)).toContain("Suspend");

    const noWt = new FakeContextMenu();
    makeService(noWt).showTaskContextMenu({ ...baseTask, folderPath: "/f" });
    await noWt.shown;
    expect(labels(noWt.lastItems)).not.toContain("Suspend");
  });

  it("labels Suspend as Unsuspend when already suspended", async () => {
    const menu = new FakeContextMenu();
    makeService(menu).showTaskContextMenu({
      ...baseTask,
      worktreePath: "/wt",
      isSuspended: true,
    });
    await menu.shown;
    expect(labels(menu.lastItems)).toContain("Unsuspend");
    expect(labels(menu.lastItems)).not.toContain("Suspend");
  });

  it("offers Stop task only for a stoppable run", async () => {
    const running = new FakeContextMenu();
    const result = makeService(running).showTaskContextMenu({
      ...baseTask,
      canStop: true,
    });
    await running.shown;
    findItem(running.lastItems, "Stop task").click();
    expect(await result).toEqual({ action: { type: "stop" } });

    const idle = new FakeContextMenu();
    makeService(idle).showTaskContextMenu(baseTask);
    await idle.shown;
    expect(labels(idle.lastItems)).not.toContain("Stop task");
  });

  it("hides Add to Command Center when already in it", async () => {
    const inCc = new FakeContextMenu();
    makeService(inCc).showTaskContextMenu({
      ...baseTask,
      isInCommandCenter: true,
    });
    await inCc.shown;
    expect(labels(inCc.lastItems)).not.toContain("Add to Command Center");
  });

  it("disables Add to Command Center when there is no empty cell", async () => {
    const menu = new FakeContextMenu();
    makeService(menu).showTaskContextMenu({
      ...baseTask,
      isInCommandCenter: false,
      hasEmptyCommandCenterCell: false,
    });
    await menu.shown;
    expect(findItem(menu.lastItems, "Add to Command Center").enabled).toBe(
      false,
    );
  });

  it("resolves to null when the menu is dismissed", async () => {
    const menu = new FakeContextMenu();
    const result = makeService(menu).showTaskContextMenu(baseTask);
    await menu.shown;
    menu.lastOptions?.onDismiss?.();
    expect(await result).toEqual({ action: null });
  });

  it("gates a confirm-protected item on dialog confirmation", async () => {
    const confirmed = new FakeContextMenu();
    const okResult = makeService(
      confirmed,
      dialogReturning(1),
    ).showTaskContextMenu(baseTask);
    await confirmed.shown;
    findItem(confirmed.lastItems, "Archive prior tasks").click();
    expect(await okResult).toEqual({ action: { type: "archive-prior" } });

    const cancelled = new FakeContextMenu();
    const cancelResult = makeService(
      cancelled,
      dialogReturning(0),
    ).showTaskContextMenu(baseTask);
    await cancelled.shown;
    findItem(cancelled.lastItems, "Archive prior tasks").click();
    expect(await cancelResult).toEqual({ action: null });
  });
});

describe("ContextMenuService.showBulkTaskContextMenu", () => {
  it("labels the archive action with the task count and gates on confirm", async () => {
    const menu = new FakeContextMenu();
    const result = makeService(
      menu,
      dialogReturning(1),
    ).showBulkTaskContextMenu({ taskCount: 3 });
    await menu.shown;
    expect(labels(menu.lastItems)).toEqual(["Archive 3 tasks"]);
    findItem(menu.lastItems, "Archive 3 tasks").click();
    expect(await result).toEqual({ action: { type: "archive" } });
  });
});

describe("ContextMenuService.confirmDeleteTask", () => {
  it("returns confirmed=true/false from the dialog response", async () => {
    const menu = new FakeContextMenu();
    expect(
      await makeService(menu, dialogReturning(1)).confirmDeleteTask({
        taskTitle: "x",
        hasWorktree: true,
      }),
    ).toEqual({ confirmed: true });
    expect(
      await makeService(menu, dialogReturning(0)).confirmDeleteTask({
        taskTitle: "x",
        hasWorktree: false,
      }),
    ).toEqual({ confirmed: false });
  });
});
