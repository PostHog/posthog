import { open } from "node:fs/promises";
import type { IFeedbackContext } from "@posthog/platform/feedback-context";
import { MAIN_WINDOW_SERVICE } from "@posthog/platform/main-window";
import { inject, injectable } from "inversify";
import { getLogFilePath } from "../utils/logger";
import type { ElectronMainWindow } from "./electron-main-window";

const MAX_SCREENSHOT_BYTES = 240 * 1024;
const MAX_LOG_BYTES = 16 * 1024;

@injectable()
export class ElectronFeedbackContext implements IFeedbackContext {
  public constructor(
    @inject(MAIN_WINDOW_SERVICE)
    private readonly mainWindow: ElectronMainWindow,
  ) {}

  public async captureScreenshot(): Promise<string | null> {
    const browserWindow = this.mainWindow.getBrowserWindow();
    if (!browserWindow) return null;

    const captured = await browserWindow.webContents.capturePage();
    if (captured.isEmpty()) return null;
    const size = captured.getSize();
    const widths = [1_200, 900, 720];
    const qualities = [65, 55, 45];

    for (let index = 0; index < widths.length; index += 1) {
      const resized = captured.resize({
        width: Math.min(size.width, widths[index]),
      });
      const jpeg = resized.toJPEG(qualities[index]);
      if (jpeg.byteLength <= MAX_SCREENSHOT_BYTES) {
        return `data:image/jpeg;base64,${jpeg.toString("base64")}`;
      }
    }

    return null;
  }

  public async readRecentLogs(): Promise<string | null> {
    let handle: Awaited<ReturnType<typeof open>> | undefined;
    try {
      handle = await open(getLogFilePath(), "r");
      const { size } = await handle.stat();
      if (size === 0) return null;

      const length = Math.min(size, MAX_LOG_BYTES);
      const buffer = Buffer.alloc(length);
      const { bytesRead } = await handle.read(buffer, 0, length, size - length);
      const content = buffer.subarray(0, bytesRead).toString("utf8");

      if (length === size) return content;
      const firstLineEnd = content.indexOf("\n");
      return firstLineEnd === -1 ? content : content.slice(firstLineEnd + 1);
    } catch {
      return null;
    } finally {
      if (handle) await handle.close().catch(() => undefined);
    }
  }
}
