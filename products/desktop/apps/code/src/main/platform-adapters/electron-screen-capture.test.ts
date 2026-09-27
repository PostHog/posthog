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
  contentSize: [number, number] = [2_000, 5_000],
) {
  const webContents = {
    capturePage: vi.fn(capturePage),
    getZoomFactor: () => zoom,
  };
  const mainWindow = {
    getBrowserWindow: () => ({
      webContents,
      getContentSize: () => contentSize,
    }),
  };
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

  it("clips the region to the window before it captures", async () => {
    const { capture, webContents } = makeCapture(
      async () => image(200, 100),
      1,
      [1_000, 700],
    );

    await capture.captureRegion({
      x: 800,
      y: 600,
      width: 9_000,
      height: 9_000,
    });
    expect(webContents.capturePage).toHaveBeenCalledWith({
      x: 800,
      y: 600,
      width: 200,
      height: 100,
    });
  });

  it.each([
    ["smaller than a pixel", { x: 10, y: 10, width: 0.2, height: 0.2 }],
    ["outside the window", { x: 3_000, y: 10, width: 50, height: 50 }],
  ])("never captures the whole page for a region %s", async (_name, region) => {
    const { capture, webContents } = makeCapture(async () => image(1, 1));

    await expect(capture.captureRegion(region)).resolves.toBeNull();
    expect(webContents.capturePage).not.toHaveBeenCalled();
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
