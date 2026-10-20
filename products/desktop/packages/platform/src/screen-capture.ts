export interface CaptureRegion {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface IScreenCapture {
  captureRegion(region: CaptureRegion): Promise<string | null>;
}

export const SCREEN_CAPTURE_SERVICE = Symbol.for(
  "posthog.platform.screenCapture",
);
