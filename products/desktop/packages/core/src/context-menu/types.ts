export interface ConfirmOptions {
  title: string;
  message: string;
  detail: string;
  confirmLabel: string;
}

export interface ActionItemDef<T> {
  type: "item";
  label: string;
  action: T;
  accelerator?: string;
  enabled?: boolean;
  icon?: string;
  confirm?: ConfirmOptions;
}

export interface SubmenuItemDef<T> {
  type: "submenu";
  label: string;
  items: Array<{
    label: string;
    icon?: string;
    action: T;
  }>;
}

export interface DisabledItemDef {
  type: "disabled";
  label: string;
}

export interface SeparatorDef {
  type: "separator";
}

export type MenuItemDef<T> =
  | ActionItemDef<T>
  | SubmenuItemDef<T>
  | DisabledItemDef
  | SeparatorDef;
