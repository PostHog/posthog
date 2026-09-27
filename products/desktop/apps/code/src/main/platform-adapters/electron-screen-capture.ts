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
    const capture = await withTimeout(
      browserWindow.webContents.capturePage({
        x: Math.round(region.x * zoom),
        y: Math.round(region.y * zoom),
        width: Math.round(region.width * zoom),
        height: Math.round(region.height * zoom),
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
            width: Math.round(width * scale),
            height: Math.round(height * scale),
          })
        : image;
    return resized.toDataURL();
  }
}
