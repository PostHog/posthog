import type {
  ConfirmOptions,
  DialogSeverity,
  IDialog,
  PickFileOptions,
} from "@posthog/platform/dialog";
import {
  BrowserWindow,
  dialog,
  type MessageBoxOptions,
  type OpenDialogOptions,
} from "electron";
import { injectable } from "inversify";

type OpenDialogProperty = NonNullable<OpenDialogOptions["properties"]>[number];

function severityToType(severity?: DialogSeverity): MessageBoxOptions["type"] {
  return severity ?? "none";
}

/**
 * Resolve the window to parent a native dialog to.
 *
 * `BrowserWindow.getFocusedWindow()` returns `null` whenever the app has no
 * focused window — which happens during onboarding flows that hand focus to
 * external windows (OS auth, the GitHub device-login browser tab, etc.). An
 * unparented dialog can then open behind the app window or off-screen, looking
 * completely unresponsive to the user. Fall back to a visible window and focus
 * it so the dialog is always parented to and rendered on top of a real window.
 */
function resolveDialogParent(): BrowserWindow | null {
  const focused = BrowserWindow.getFocusedWindow();
  if (focused) return focused;
  const windows = BrowserWindow.getAllWindows();
  const parent = windows.find((w) => w.isVisible()) ?? windows[0] ?? null;
  parent?.focus();
  return parent;
}

function buildProperties(options: PickFileOptions): OpenDialogProperty[] {
  const properties: OpenDialogProperty[] = ["treatPackageAsDirectory"];
  if (options.filesAndDirectories) {
    // Electron on Windows cannot combine openFile + openDirectory in one
    // dialog; callers must branch and request each mode separately there.
    properties.push("openFile", "openDirectory");
  } else if (options.directories) {
    properties.push("openDirectory");
  } else {
    properties.push("openFile");
  }
  if (options.multiple) properties.push("multiSelections");
  if (options.createDirectories) properties.push("createDirectory");
  return properties;
}

@injectable()
export class ElectronDialog implements IDialog {
  public async confirm(options: ConfirmOptions): Promise<number> {
    const parent = resolveDialogParent();
    const electronOptions: MessageBoxOptions = {
      type: severityToType(options.severity),
      title: options.title,
      message: options.message,
      detail: options.detail,
      buttons: options.options,
      defaultId: options.defaultIndex,
      cancelId: options.cancelIndex,
    };
    const result = parent
      ? await dialog.showMessageBox(parent, electronOptions)
      : await dialog.showMessageBox(electronOptions);
    return result.response;
  }

  public async pickFile(options: PickFileOptions): Promise<string[]> {
    const parent = resolveDialogParent();
    const electronOptions: OpenDialogOptions = {
      title: options.title,
      properties: buildProperties(options),
    };
    const result = parent
      ? await dialog.showOpenDialog(parent, electronOptions)
      : await dialog.showOpenDialog(electronOptions);
    return result.canceled ? [] : result.filePaths;
  }
}
