import type { IMainWindow } from "@posthog/platform/main-window";
import { app, type BrowserWindow } from "electron";
import { injectable } from "inversify";
import { adjustWindowZoom, ZOOM_STEP } from "../zoom";

@injectable()
export class ElectronMainWindow implements IMainWindow {
  private mainWindowGetter: (() => BrowserWindow | null) | null = null;

  public setMainWindowGetter(getter: () => BrowserWindow | null): void {
    this.mainWindowGetter = getter;
  }

  public getBrowserWindow(): BrowserWindow | null {
    return this.mainWindowGetter?.() ?? null;
  }

  public focus(): void {
    this.getBrowserWindow()?.focus();
  }

  public isFocused(): boolean {
    return this.getBrowserWindow()?.isFocused() ?? false;
  }

  public isMinimized(): boolean {
    return this.getBrowserWindow()?.isMinimized() ?? false;
  }

  public restore(): void {
    this.getBrowserWindow()?.restore();
  }

  public onFocus(handler: () => void): () => void {
    const listener = () => handler();
    app.on("browser-window-focus", listener);
    return () => app.off("browser-window-focus", listener);
  }

  public zoomIn(): void {
    const window = this.getBrowserWindow();
    if (window) adjustWindowZoom(window, ZOOM_STEP);
  }

  public zoomOut(): void {
    const window = this.getBrowserWindow();
    if (window) adjustWindowZoom(window, -ZOOM_STEP);
  }

  public resetZoom(): void {
    const window = this.getBrowserWindow();
    if (window) adjustWindowZoom(window, "reset");
  }
}
