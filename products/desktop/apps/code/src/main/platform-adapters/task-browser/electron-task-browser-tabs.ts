import { PAGE_WORLD_ID } from "@posthog/core/task-browser/page-scripts";
import type {
  ITaskBrowserTabs,
  TaskBrowserImage,
  TaskBrowserRect,
} from "@posthog/platform/task-browser";
import { session, type WebContents, webContents } from "electron";
import { injectable } from "inversify";
import { TASK_BROWSER_PARTITION } from "../../../shared/constants";

const CAPTURE_TIMEOUT_MS = 2_000;
const LOAD_TIMEOUT_MS = 10_000;
const SCREENSHOT_MAX_WIDTH = 1_280;
const SCREENSHOT_QUALITY = 80;

@injectable()
export class ElectronTaskBrowserTabs implements ITaskBrowserTabs {
  isWebview(tabId: number): boolean {
    return webContents.fromId(tabId)?.getType() === "webview";
  }

  isDestroyed(tabId: number): boolean {
    const contents = webContents.fromId(tabId);
    return !contents || contents.isDestroyed();
  }

  onConsole(tabId: number, listener: (text: string) => void): void {
    this.contents(tabId).on(
      "console-message",
      (event: unknown, ...legacy: unknown[]) => {
        const details = event as { message?: string; level?: string | number };
        const message =
          typeof details.message === "string"
            ? details.message
            : String(legacy[1] ?? "");
        const level = details.level ?? legacy[0] ?? "log";
        listener(`[${level}] ${message}`);
      },
    );
  }

  onDestroyed(tabId: number, listener: () => void): void {
    this.contents(tabId).once("destroyed", listener);
  }

  url(tabId: number): string {
    return this.contents(tabId).getURL();
  }

  title(tabId: number): string {
    return this.contents(tabId).getTitle();
  }

  waitForLoad(tabId: number): Promise<void> {
    const contents = this.contents(tabId);
    if (!contents.isLoading()) return Promise.resolve();
    return new Promise((resolve) => {
      const done = () => {
        clearTimeout(timer);
        resolve();
      };
      const timer = setTimeout(done, LOAD_TIMEOUT_MS);
      contents.once("did-stop-loading", done);
    });
  }

  async runScript<T>(tabId: number, code: string): Promise<T> {
    await this.waitForLoad(tabId);
    return (await this.contents(tabId).executeJavaScriptInIsolatedWorld(
      PAGE_WORLD_ID,
      [{ code }],
    )) as T;
  }

  zoom(tabId: number): number {
    return this.contents(tabId).getZoomFactor();
  }

  async capture(
    tabId: number,
    rect: TaskBrowserRect | undefined,
  ): Promise<TaskBrowserImage | null> {
    const image = await Promise.race([
      this.contents(tabId)
        .capturePage(rect)
        .catch(() => null),
      new Promise<null>((resolve) =>
        setTimeout(() => resolve(null), CAPTURE_TIMEOUT_MS),
      ),
    ]);
    if (!image || image.isEmpty()) return null;
    const resized =
      image.getSize().width > SCREENSHOT_MAX_WIDTH
        ? image.resize({ width: SCREENSHOT_MAX_WIDTH })
        : image;
    return {
      data: resized.toJPEG(SCREENSHOT_QUALITY).toString("base64"),
      mimeType: "image/jpeg",
    };
  }

  click(tabId: number, x: number, y: number): void {
    const contents = this.contents(tabId);
    contents.focus();
    contents.sendInputEvent({ type: "mouseMove", x, y });
    for (const type of ["mouseDown", "mouseUp"] as const) {
      contents.sendInputEvent({ type, x, y, button: "left", clickCount: 1 });
    }
  }

  pressKey(tabId: number, key: string): void {
    const contents = this.contents(tabId);
    contents.focus();
    contents.sendInputEvent({ type: "keyDown", keyCode: key });
    if (key.length === 1)
      contents.sendInputEvent({ type: "char", keyCode: key });
    contents.sendInputEvent({ type: "keyUp", keyCode: key });
  }

  insertText(tabId: number, text: string, clear: boolean): void {
    const contents = this.contents(tabId);
    contents.focus();
    if (clear) {
      contents.sendInputEvent({ type: "keyDown", keyCode: "Backspace" });
      contents.sendInputEvent({ type: "keyUp", keyCode: "Backspace" });
    }
    if (text) void contents.insertText(text);
  }

  goBack(tabId: number): void {
    const history = this.contents(tabId).navigationHistory;
    if (history.canGoBack()) history.goBack();
  }

  goForward(tabId: number): void {
    const history = this.contents(tabId).navigationHistory;
    if (history.canGoForward()) history.goForward();
  }

  reload(tabId: number): void {
    this.contents(tabId).reload();
  }

  async load(tabId: number, url: string): Promise<void> {
    await this.contents(tabId)
      .loadURL(url)
      .catch(() => undefined);
  }

  sendCdp(tabId: number, method: string, params: object): Promise<unknown> {
    const debuggerApi = this.contents(tabId).debugger;
    if (!debuggerApi.isAttached()) debuggerApi.attach("1.3");
    return debuggerApi.sendCommand(method, params as Record<string, unknown>);
  }

  async clearBrowsingData(): Promise<void> {
    const browserSession = session.fromPartition(TASK_BROWSER_PARTITION);
    await browserSession.clearStorageData();
    await browserSession.clearCache();
  }

  private contents(tabId: number): WebContents {
    const contents = webContents.fromId(tabId);
    if (!contents || contents.isDestroyed()) {
      throw new Error("The browser tab is closed.");
    }
    return contents;
  }
}
