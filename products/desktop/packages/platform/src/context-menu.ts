export interface ContextMenuAction {
  label: string;
  icon?: string;
  enabled?: boolean;
  accelerator?: string;
  submenu?: ContextMenuItem[];
  click: () => void | Promise<void>;
}

export interface ContextMenuSeparator {
  separator: true;
}

export type ContextMenuItem = ContextMenuAction | ContextMenuSeparator;

export interface ShowContextMenuOptions {
  onDismiss?: () => void;
}

export interface IContextMenu {
  show(items: ContextMenuItem[], options?: ShowContextMenuOptions): void;
}

export const CONTEXT_MENU_SERVICE = Symbol.for("posthog.platform.contextMenu");
