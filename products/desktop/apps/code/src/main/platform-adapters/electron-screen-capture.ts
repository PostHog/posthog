import { MAIN_WINDOW_SERVICE } from "@posthog/platform/main-window";
import type {
  CaptureRegion,
  IScreenCapture,
} from "@posthog/platform/screen-capture";
import { withTimeout } from "@posthog/shared";
import { inject, injectable } from "inversify";
import type { ElectronMainWindow } from "./electron-main-window";

const CAPTURE_DEADLINE_MS = 2_000;
const MAX_WIDTH = 1_280;

@injectable()
export class ElectronScreenCapture implements IScreenCapture {
  public constructor(
    @inject(MAIN_WINDOW_SERVICE)
    private readonly mainWindow: ElectronMainWindow,
  ) {}

  public async captureRegion(region: CaptureRegion): Promise<string | null> {
    const browserWindow = this.mainWindow.getBrowserWindow();
    if (!browserWindow) return null;
    const capture = await withTimeout(
      browserWindow.webContents.capturePage({
        x: Math.round(region.x),
        y: Math.round(region.y),
        width: Math.round(region.width),
        height: Math.round(region.height),
      }),
      CAPTURE_DEADLINE_MS,
    );
    if (capture.result === "timeout" || capture.value.isEmpty()) return null;
    const image = capture.value;
    const { width } = image.getSize();
    const resized =
      width > MAX_WIDTH ? image.resize({ width: MAX_WIDTH }) : image;
    return resized.toDataURL();
  }
}
