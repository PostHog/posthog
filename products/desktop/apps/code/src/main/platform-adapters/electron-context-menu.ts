import type {
  ContextMenuAction,
  ContextMenuItem,
  IContextMenu,
  ShowContextMenuOptions,
} from "@posthog/platform/context-menu";
import { Menu, type MenuItemConstructorOptions, nativeImage } from "electron";
import { injectable } from "inversify";

const ICON_SIZE = 16;

function isSeparator(item: ContextMenuItem): item is { separator: true } {
  return "separator" in item && item.separator === true;
}

function resizeIcon(dataUrl: string): Electron.NativeImage {
  return nativeImage
    .createFromDataURL(dataUrl)
    .resize({ width: ICON_SIZE, height: ICON_SIZE });
}

function toElectronItem(item: ContextMenuItem): MenuItemConstructorOptions {
  if (isSeparator(item)) {
    return { type: "separator" };
  }
  const action = item as ContextMenuAction;
  const options: MenuItemConstructorOptions = {
    label: action.label,
    enabled: action.enabled ?? true,
    accelerator: action.accelerator,
  };
  if (action.icon) {
    options.icon = resizeIcon(action.icon);
  }
  if (action.submenu && action.submenu.length > 0) {
    options.submenu = action.submenu.map(toElectronItem);
  } else {
    options.click = () => {
      void action.click();
    };
  }
  return options;
}

@injectable()
export class ElectronContextMenu implements IContextMenu {
  public show(
    items: ContextMenuItem[],
    options?: ShowContextMenuOptions,
  ): void {
    const template = items.map(toElectronItem);
    Menu.buildFromTemplate(template).popup({
      callback: () => options?.onDismiss?.(),
    });
  }
}
