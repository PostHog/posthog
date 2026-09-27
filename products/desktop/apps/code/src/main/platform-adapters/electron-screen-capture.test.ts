import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("inversify", () => ({
  injectable: () => (target: unknown) => target,
  inject: () => () => undefined,
}));

import { ElectronScreenCapture } from "./electron-screen-capture";

function image(width: number, height: number) {
  const resize = vi.fn(
    ({ width, height }: { width: number; height: number }) => ({
      toDataURL: () => `data:image/png;${width}x${height}`,
    }),
  );
  return {
    isEmpty: () => false,
    getSize: () => ({ width, height }),
    resize,
    toDataURL: () => `data:image/png;${width}x${height}`,
  };
}

function makeCapture(
  capturePage: (rect: unknown) => Promise<unknown>,
  zoom = 1,
) {
  const webContents = {
    capturePage: vi.fn(capturePage),
    getZoomFactor: () => zoom,
  };
  const mainWindow = { getBrowserWindow: () => ({ webContents }) };
  return {
    capture: new ElectronScreenCapture(mainWindow as never),
    webContents,
  };
}

describe("ElectronScreenCapture.captureRegion", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("captures the region the page measured, at the window zoom", async () => {
    const { capture, webContents } = makeCapture(
      async () => image(600, 300),
      1.5,
    );

    await expect(
      capture.captureRegion({ x: 10, y: 20, width: 400, height: 200 }),
    ).resolves.toBe("data:image/png;600x300");
    expect(webContents.capturePage).toHaveBeenCalledWith({
      x: 15,
      y: 30,
      width: 600,
      height: 300,
    });
  });

  it("scales a tall capture so both sides fit", async () => {
    const tall = image(1_000, 4_000);
    const { capture } = makeCapture(async () => tall);

    await expect(
      capture.captureRegion({ x: 0, y: 0, width: 1_000, height: 4_000 }),
    ).resolves.toBe("data:image/png;320x1280");
  });

  it.each([
    ["the capture fails", () => Promise.reject(new Error("gone"))],
    ["the capture never settles", () => new Promise(() => {})],
  ])("gives no image when %s", async (_name, capturePage) => {
    vi.useFakeTimers();
    const { capture } = makeCapture(capturePage);

    const pending = capture.captureRegion({
      x: 0,
      y: 0,
      width: 10,
      height: 10,
    });
    await vi.advanceTimersByTimeAsync(2_000);

    await expect(pending).resolves.toBeNull();
  });
});
