import { formatBulkArchiveWarning } from "@posthog/core/sidebar/selection";
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

function findSubmenuItem(
  items: ContextMenuItem[],
  submenuLabel: string,
  itemLabel: string,
): ContextMenuAction {
  const submenu = findItem(items, submenuLabel).submenu ?? [];
  return findItem(submenu, itemLabel);
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

  it("offers Hand off only to callers that mark it available", async () => {
    // The API 404s a non-owner's handoff, so the item must stay hidden from one.
    const owner = new FakeContextMenu();
    const handedOff = makeService(owner).showTaskContextMenu({
      ...baseTask,
      canHandoff: true,
    });
    await owner.shown;
    findItem(owner.lastItems, "Hand off…").click();
    expect(await handedOff).toEqual({ action: { type: "handoff" } });

    const viewer = new FakeContextMenu();
    makeService(viewer).showTaskContextMenu(baseTask);
    await viewer.shown;
    expect(labels(viewer.lastItems)).not.toContain("Hand off…");
  });

  it("can hide Archive prior tasks for task lists without that action", async () => {
    const menu = new FakeContextMenu();
    makeService(menu).showTaskContextMenu({
      ...baseTask,
      showArchivePrior: false,
    });
    await menu.shown;
    expect(labels(menu.lastItems)).not.toContain("Archive prior tasks");
    expect(labels(menu.lastItems)).toContain("Archive");
  });

  it("lists starred channels first under File to…", async () => {
    const menu = new FakeContextMenu();
    const result = makeService(menu).showTaskContextMenu({
      ...baseTask,
      channels: [
        {
          id: "0",
          name: "personal",
          channelType: "personal",
          starred: true,
        },
        { id: "1", name: "alpha" },
        { id: "2", name: "beta", starred: true },
        { id: "3", name: "gamma" },
        { id: "4", name: "delta", starred: true },
      ],
    });
    await menu.shown;
    const submenu = findItem(menu.lastItems, "File to…").submenu ?? [];
    expect(labels(submenu)).toEqual([
      "personal",
      "#beta",
      "#delta",
      "#alpha",
      "#gamma",
    ]);
    findSubmenuItem(menu.lastItems, "File to…", "#delta").click();
    expect(await result).toEqual({
      action: { type: "file-to-channel", channelId: "4" },
    });
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
  it("labels every action with the session count", async () => {
    const menu = new FakeContextMenu();
    const result = makeService(menu).showBulkTaskContextMenu({ taskCount: 3 });
    await menu.shown;
    expect(labels(menu.lastItems)).toEqual([
      "Pin 3 sessions",
      "Add 3 sessions to Command Center",
      "Archive 3 sessions",
    ]);
    findItem(menu.lastItems, "Add 3 sessions to Command Center").click();
    expect(await result).toEqual({ action: { type: "add-to-command-center" } });
  });

  it.each([
    { allPinned: false, expected: "Pin 3 sessions" },
    { allPinned: true, expected: "Unpin 3 sessions" },
  ])(
    "offers $expected when allPinned=$allPinned",
    async ({ allPinned, expected }) => {
      const menu = new FakeContextMenu();
      const result = makeService(menu).showBulkTaskContextMenu({
        taskCount: 3,
        allPinned,
      });
      await menu.shown;
      findItem(menu.lastItems, expected).click();
      expect(await result).toEqual({ action: { type: "pin" } });
    },
  );

  it("omits the File to submenu when there are no channels", async () => {
    const menu = new FakeContextMenu();
    makeService(menu).showBulkTaskContextMenu({ taskCount: 2, channels: [] });
    await menu.shown;
    expect(labels(menu.lastItems)).not.toContain("File to…");
  });

  it("resolves a channel from the File to submenu", async () => {
    const menu = new FakeContextMenu();
    const result = makeService(menu).showBulkTaskContextMenu({
      taskCount: 2,
      // Stored bare, shown with the hash the menu adds.
      channels: [{ id: "c1", name: "support" }],
    });
    await menu.shown;
    findSubmenuItem(menu.lastItems, "File to…", "#support").click();
    expect(await result).toEqual({
      action: { type: "file-to-channel", channelId: "c1" },
    });
  });

  it("lists starred channels first under File to…", async () => {
    const menu = new FakeContextMenu();
    makeService(menu).showBulkTaskContextMenu({
      taskCount: 2,
      channels: [
        { id: "c1", name: "support" },
        { id: "c2", name: "design", starred: true },
        {
          id: "c3",
          name: "personal",
          channelType: "personal",
          starred: true,
        },
      ],
    });
    await menu.shown;
    const submenu = findItem(menu.lastItems, "File to…").submenu ?? [];
    expect(labels(submenu)).toEqual(["#design", "personal", "#support"]);
  });

  it("gates archive on confirmation", async () => {
    const menu = new FakeContextMenu();
    const result = makeService(
      menu,
      dialogReturning(0),
    ).showBulkTaskContextMenu({ taskCount: 3 });
    await menu.shown;
    findItem(menu.lastItems, "Archive 3 sessions").click();
    expect(await result).toEqual({ action: null });
  });

  // The native confirm and the action bar's dialog must warn about the same
  // things; both compose their detail with formatBulkArchiveWarning.
  it("warns in the archive confirm about running sessions and cloud sandboxes", async () => {
    const menu = new FakeContextMenu();
    let confirmOptions: ConfirmOptions | undefined;
    const dialog = {
      confirm: async (options: ConfirmOptions) => {
        confirmOptions = options;
        return 1;
      },
    } as IDialog;
    const result = makeService(menu, dialog).showBulkTaskContextMenu({
      taskCount: 3,
      runningCount: 2,
      stopsCloudSandbox: true,
    });
    await menu.shown;
    findItem(menu.lastItems, "Archive 3 sessions").click();
    await result;
    expect(confirmOptions?.detail).toBe(
      formatBulkArchiveWarning({ running: 2, stopsCloudSandbox: true }),
    );
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
