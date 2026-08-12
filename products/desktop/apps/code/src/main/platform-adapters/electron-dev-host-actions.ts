import type { IDevHostActions } from "@posthog/platform/dev-host-actions";
import { app, BrowserWindow, shell } from "electron";
import { injectable } from "inversify";

@injectable()
export class ElectronDevHostActions implements IDevHostActions {
  public async openPath(path: string): Promise<void> {
    await shell.openPath(path);
  }

  public reloadAllWindows(): void {
    for (const window of BrowserWindow.getAllWindows()) {
      window.webContents.reload();
    }
  }

  public relaunch(): void {
    app.relaunch();
    app.exit(0);
  }

  public crash(): void {
    process.crash();
  }
}
