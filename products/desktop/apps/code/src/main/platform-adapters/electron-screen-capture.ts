import { MAIN_WINDOW_SERVICE } from "@posthog/platform/main-window";
import type {
  CaptureRegion,
  IScreenCapture,
} from "@posthog/platform/screen-capture";
import { withTimeout } from "@posthog/shared";
import { inject, injectable } from "inversify";
import type { ElectronMainWindow } from "./electron-main-window";

const CAPTURE_DEADLINE_MS = 2_000;
const MAX_SIDE = 1_280;

function clamp(value: number, limit: number): number {
  return Math.min(Math.max(value, 0), limit);
}

@injectable()
export class ElectronScreenCapture implements IScreenCapture {
  public constructor(
    @inject(MAIN_WINDOW_SERVICE)
    private readonly mainWindow: ElectronMainWindow,
  ) {}

  public async captureRegion(region: CaptureRegion): Promise<string | null> {
    const browserWindow = this.mainWindow.getBrowserWindow();
    if (!browserWindow) return null;
    const zoom = browserWindow.webContents.getZoomFactor();
    const [contentWidth, contentHeight] = browserWindow.getContentSize();
    const left = clamp(Math.round(region.x * zoom), contentWidth);
    const top = clamp(Math.round(region.y * zoom), contentHeight);
    const right = clamp(
      Math.round((region.x + region.width) * zoom),
      contentWidth,
    );
    const bottom = clamp(
      Math.round((region.y + region.height) * zoom),
      contentHeight,
    );
    if (right - left < 1 || bottom - top < 1) return null;
    const capture = await withTimeout(
      browserWindow.webContents.capturePage({
        x: left,
        y: top,
        width: right - left,
        height: bottom - top,
      }),
      CAPTURE_DEADLINE_MS,
    ).catch(() => null);
    if (!capture || capture.result === "timeout" || capture.value.isEmpty()) {
      return null;
    }
    const image = capture.value;
    const { width, height } = image.getSize();
    const scale = Math.min(1, MAX_SIDE / width, MAX_SIDE / height);
    const resized =
      scale < 1
        ? image.resize({
            width: Math.max(1, Math.round(width * scale)),
            height: Math.max(1, Math.round(height * scale)),
          })
        : image;
    return resized.toDataURL();
  }
}
