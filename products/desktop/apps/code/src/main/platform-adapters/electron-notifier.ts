import { MAIN_WINDOW_SERVICE } from "@posthog/platform/main-window";
import type { INotifier, NotifyOptions } from "@posthog/platform/notifier";
import { app, Notification } from "electron";
import { inject, injectable } from "inversify";
import type { ElectronMainWindow } from "./electron-main-window";

@injectable()
export class ElectronNotifier implements INotifier {
  // Retain shown notifications so V8 doesn't GC the JS wrapper (and its
  // `click` listener) before the user interacts. Without this, the OS still
  // shows the notification and macOS will even focus the app on click, but
  // the JS click handler never fires — so any in-app routing tied to it
  // (e.g. switching to the task the notification was about) silently breaks.
  private readonly active = new Set<Notification>();

  constructor(
    @inject(MAIN_WINDOW_SERVICE)
    private readonly mainWindow: ElectronMainWindow,
  ) {}

  public isSupported(): boolean {
    return Notification.isSupported();
  }

  public notify(options: NotifyOptions): void {
    const notification = new Notification({
      title: options.title,
      body: options.body,
      silent: options.silent,
    });
    this.active.add(notification);
    const release = () => this.active.delete(notification);
    notification.once("close", release);
    notification.once("click", release);
    notification.once("failed", release);
    if (options.onClick) {
      notification.on("click", options.onClick);
    }
    notification.show();
  }

  public setUnreadIndicator(on: boolean): void {
    if (on) {
      app.dock?.setBadge("•");
    } else {
      app.dock?.setBadge("");
      this.mainWindow.getBrowserWindow()?.flashFrame(false);
    }
  }

  public requestAttention(): void {
    app.dock?.bounce("informational");
    this.mainWindow.getBrowserWindow()?.flashFrame(true);
  }
}
