import {
  CONTEXT_MENU_SERVICE,
  type ContextMenuItem,
  type IContextMenu,
} from "@posthog/platform/context-menu";
import { DIALOG_SERVICE, type IDialog } from "@posthog/platform/dialog";
import { inject, injectable } from "inversify";
import {
  CONTEXT_MENU_EXTERNAL_APPS_SERVICE,
  type ContextMenuExternalApp,
  type IContextMenuExternalApps,
} from "./identifiers";
import type {
  ArchivedTaskAction,
  ArchivedTaskContextMenuInput,
  ArchivedTaskContextMenuResult,
  BulkTaskAction,
  BulkTaskContextMenuInput,
  ConfirmDeleteArchivedTaskInput,
  ConfirmDeleteArchivedTaskResult,
  ConfirmDeleteTaskInput,
  ConfirmDeleteTaskResult,
  FileAction,
  FileContextMenuInput,
  FileContextMenuResult,
  FolderAction,
  FolderContextMenuInput,
  FolderContextMenuResult,
  SplitContextMenuResult,
  SplitDirection,
  TabAction,
  TabContextMenuInput,
  TabContextMenuResult,
  TaskAction,
  TaskContextMenuInput,
  TaskContextMenuResult,
} from "./schemas";
import type {
  ActionItemDef,
  ConfirmOptions,
  MenuItemDef,
  SeparatorDef,
} from "./types";

@injectable()
export class ContextMenuService {
  constructor(
    @inject(CONTEXT_MENU_EXTERNAL_APPS_SERVICE)
    private readonly externalApps: IContextMenuExternalApps,
    @inject(DIALOG_SERVICE)
    private readonly dialog: IDialog,
    @inject(CONTEXT_MENU_SERVICE)
    private readonly contextMenu: IContextMenu,
  ) {}

  private async getExternalAppsData() {
    const [apps, lastUsed] = await Promise.all([
      this.externalApps.getDetectedApps(),
      this.externalApps.getLastUsed(),
    ]);
    return { apps, lastUsedAppId: lastUsed.lastUsedApp };
  }

  async confirmDeleteTask(
    input: ConfirmDeleteTaskInput,
  ): Promise<ConfirmDeleteTaskResult> {
    const confirmed = await this.confirm({
      title: "Delete Task",
      message: `Delete "${input.taskTitle}"?`,
      detail: input.hasWorktree
        ? "This will permanently delete the task and its associated worktree."
        : "This will permanently delete the task.",
      confirmLabel: "Delete",
    });
    return { confirmed };
  }

  async confirmDeleteArchivedTask(
    input: ConfirmDeleteArchivedTaskInput,
  ): Promise<ConfirmDeleteArchivedTaskResult> {
    const confirmed = await this.confirm({
      title: "Delete Archived Task",
      message: `Delete "${input.taskTitle}"?`,
      detail: "This will permanently delete the archived task.",
      confirmLabel: "Delete",
    });
    return { confirmed };
  }

  async confirmDeleteWorktree({
    worktreePath,
    linkedTaskCount,
  }: {
    worktreePath: string;
    linkedTaskCount: number;
  }): Promise<{ confirmed: boolean }> {
    const confirmed = await this.confirm({
      title: "Delete Worktree",
      message: `Delete worktree at ${worktreePath}?`,
      detail:
        linkedTaskCount > 0
          ? `This will remove ${linkedTaskCount} linked task${linkedTaskCount === 1 ? "" : "s"} and delete the worktree.`
          : "This will delete the worktree from disk.",
      confirmLabel: "Delete",
    });
    return { confirmed };
  }

  async showTaskContextMenu(
    input: TaskContextMenuInput,
  ): Promise<TaskContextMenuResult> {
    const {
      worktreePath,
      folderPath,
      isPinned,
      isSuspended,
      canStop,
      isInCommandCenter,
      hasEmptyCommandCenterCell,
      channels,
    } = input;
    const { apps, lastUsedAppId } = await this.getExternalAppsData();
    const hasPath = worktreePath || folderPath;
    const fileToItems: MenuItemDef<TaskAction>[] =
      channels && channels.length > 0
        ? [
            this.separator(),
            {
              type: "submenu",
              label: "File to…",
              items: channels.map((c) => ({
                label: c.name,
                action: {
                  type: "file-to-channel" as const,
                  channelId: c.id,
                },
              })),
            },
          ]
        : [];

    return this.showMenu<TaskAction>([
      this.item(isPinned ? "Unpin" : "Pin", { type: "pin" }),
      this.item("Rename", { type: "rename" }),
      ...(canStop
        ? [this.separator(), this.item("Stop task", { type: "stop" as const })]
        : []),
      ...(worktreePath
        ? [
            this.separator(),
            this.item(isSuspended ? "Unsuspend" : "Suspend", {
              type: "suspend" as const,
            }),
          ]
        : []),
      ...(hasPath
        ? [
            ...(worktreePath ? [] : [this.separator()]),
            ...this.externalAppItems<TaskAction>(apps, lastUsedAppId),
          ]
        : []),
      ...(!isInCommandCenter
        ? [
            this.separator(),
            this.item(
              "Add to Command Center",
              { type: "add-to-command-center" as const },
              { enabled: hasEmptyCommandCenterCell ?? true },
            ),
          ]
        : []),
      ...fileToItems,
      this.separator(),
      this.item("Archive", { type: "archive" }),
      this.item(
        "Archive prior tasks",
        { type: "archive-prior" },
        {
          confirm: {
            title: "Archive Prior Tasks",
            message: "Archive all tasks older than this one?",
            detail:
              "This will archive every task created before this one. You can unarchive them later.",
            confirmLabel: "Archive",
          },
        },
      ),
    ]);
  }

  async showBulkTaskContextMenu(
    input: BulkTaskContextMenuInput,
  ): Promise<{ action: BulkTaskAction | null }> {
    const { taskCount } = input;
    const label = `Archive ${taskCount} tasks`;
    return this.showMenu<BulkTaskAction>([
      this.item(
        label,
        { type: "archive" },
        {
          confirm: {
            title: "Archive Tasks",
            message: `Archive ${taskCount} tasks?`,
            detail: "You can unarchive them later.",
            confirmLabel: "Archive",
          },
        },
      ),
    ]);
  }

  async showArchivedTaskContextMenu(
    input: ArchivedTaskContextMenuInput,
  ): Promise<ArchivedTaskContextMenuResult> {
    return this.showMenu<ArchivedTaskAction>([
      this.item("Unarchive", { type: "restore" }),
      this.item(
        "Delete",
        { type: "delete" },
        {
          confirm: {
            title: "Delete Archived Task",
            message: `Delete "${input.taskTitle}"?`,
            detail: "This will permanently delete the archived task.",
            confirmLabel: "Delete",
          },
        },
      ),
    ]);
  }

  async showFolderContextMenu(
    input: FolderContextMenuInput,
  ): Promise<FolderContextMenuResult> {
    const { folderName, folderPath } = input;
    const { apps, lastUsedAppId } = await this.getExternalAppsData();

    return this.showMenu<FolderAction>([
      this.item(
        "Remove folder",
        { type: "remove" },
        {
          confirm: {
            title: "Remove Folder",
            message: `Remove "${folderName}"?`,
            detail:
              "This will clean up any worktrees but keep your folder and tasks intact.",
            confirmLabel: "Remove",
          },
        },
      ),
      ...(folderPath
        ? [
            this.separator(),
            ...this.externalAppItems<FolderAction>(apps, lastUsedAppId),
          ]
        : []),
    ]);
  }

  async showTabContextMenu(
    input: TabContextMenuInput,
  ): Promise<TabContextMenuResult> {
    const { canClose, filePath } = input;
    const { apps, lastUsedAppId } = await this.getExternalAppsData();

    return this.showMenu<TabAction>([
      this.item(
        "Close tab",
        { type: "close" },
        {
          accelerator: "CmdOrCtrl+W",
          enabled: canClose,
        },
      ),
      this.item("Close other tabs", { type: "close-others" }),
      this.item("Close tabs to the right", { type: "close-right" }),
      ...(filePath
        ? [
            this.separator(),
            ...this.externalAppItems<TabAction>(apps, lastUsedAppId),
          ]
        : []),
    ]);
  }

  async showSplitContextMenu(): Promise<SplitContextMenuResult> {
    const result = await this.showMenu<SplitDirection>([
      this.item("Split right", "right"),
      this.item("Split left", "left"),
      this.item("Split down", "down"),
      this.item("Split up", "up"),
    ]);
    return { direction: result.action };
  }

  async showFileContextMenu(
    input: FileContextMenuInput,
  ): Promise<FileContextMenuResult> {
    const { apps, lastUsedAppId } = await this.getExternalAppsData();

    return this.showMenu<FileAction>([
      ...(input.showCollapseAll
        ? [
            this.item<FileAction>("Collapse All", { type: "collapse-all" }),
            this.separator(),
          ]
        : []),
      ...this.externalAppItems<FileAction>(apps, lastUsedAppId),
    ]);
  }

  private externalAppItems<T>(
    apps: ContextMenuExternalApp[],
    lastUsedAppId?: string,
  ): MenuItemDef<T>[] {
    if (apps.length === 0) {
      return [this.disabled("No external apps detected")];
    }

    const lastUsedApp = apps.find((app) => app.id === lastUsedAppId) || apps[0];
    const openIn = (appId: string): T =>
      ({ type: "external-app", action: { type: "open-in-app", appId } }) as T;
    return [
      this.item(`Open in ${lastUsedApp.name}`, openIn(lastUsedApp.id)),
      {
        type: "submenu",
        label: "Open in",
        items: apps.map((app) => ({
          label: app.name,
          icon: app.icon,
          action: openIn(app.id),
        })),
      },
    ];
  }

  private item<T>(
    label: string,
    action: T,
    options?: Partial<Omit<ActionItemDef<T>, "type" | "label" | "action">>,
  ): ActionItemDef<T> {
    return { type: "item", label, action, ...options };
  }

  private separator(): SeparatorDef {
    return { type: "separator" };
  }

  private disabled(label: string): MenuItemDef<never> {
    return { type: "disabled", label };
  }

  private showMenu<T>(items: MenuItemDef<T>[]): Promise<{ action: T | null }> {
    return new Promise((resolve) => {
      let pendingConfirm = false;

      const toContextMenuItem = (def: MenuItemDef<T>): ContextMenuItem => {
        switch (def.type) {
          case "separator":
            return { separator: true };
          case "disabled":
            return { label: def.label, enabled: false, click: () => {} };
          case "submenu":
            return {
              label: def.label,
              submenu: def.items.map((sub) => ({
                label: sub.label,
                icon: sub.icon,
                click: () => resolve({ action: sub.action }),
              })),
              click: () => {},
            };
          case "item": {
            const confirmOptions = def.confirm;
            const click = confirmOptions
              ? async () => {
                  pendingConfirm = true;
                  const confirmed = await this.confirm(confirmOptions);
                  resolve({ action: confirmed ? def.action : null });
                }
              : () => resolve({ action: def.action });
            return {
              label: def.label,
              enabled: def.enabled,
              accelerator: def.accelerator,
              icon: def.icon,
              click,
            };
          }
        }
      };

      this.contextMenu.show(items.map(toContextMenuItem), {
        onDismiss: () => {
          if (!pendingConfirm) resolve({ action: null });
        },
      });
    });
  }

  private async confirm(options: ConfirmOptions): Promise<boolean> {
    const response = await this.dialog.confirm({
      severity: "question",
      title: options.title,
      message: options.message,
      detail: options.detail,
      options: ["Cancel", options.confirmLabel],
      defaultIndex: 1,
      cancelIndex: 0,
    });
    return response === 1;
  }
}
