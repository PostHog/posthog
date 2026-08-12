import type {
  ExternalAppAction,
  TaskAction,
} from "@posthog/core/context-menu/schemas";

export type TaskContextMenuIntent =
  | { type: "rename" }
  | { type: "pin" }
  | { type: "suspend" }
  | { type: "stop" }
  | { type: "restore" }
  | { type: "archive" }
  | { type: "archive-prior" }
  | { type: "delete" }
  | { type: "add-to-command-center" }
  | { type: "file-to-channel"; channelId: string }
  | { type: "external-app"; action: ExternalAppAction };

export function resolveTaskContextMenuIntent(
  action: TaskAction,
  flags: { isSuspended?: boolean },
): TaskContextMenuIntent {
  switch (action.type) {
    case "rename":
      return { type: "rename" };
    case "pin":
      return { type: "pin" };
    case "suspend":
      return flags.isSuspended ? { type: "restore" } : { type: "suspend" };
    case "stop":
      return { type: "stop" };
    case "archive":
      return { type: "archive" };
    case "archive-prior":
      return { type: "archive-prior" };
    case "delete":
      return { type: "delete" };
    case "add-to-command-center":
      return { type: "add-to-command-center" };
    case "file-to-channel":
      return { type: "file-to-channel", channelId: action.channelId };
    case "external-app":
      return { type: "external-app", action: action.action };
  }
}

export function resolveExternalAppPath(
  worktreePath: string | undefined,
  folderPath: string | undefined,
): string | undefined {
  return worktreePath ?? folderPath;
}
