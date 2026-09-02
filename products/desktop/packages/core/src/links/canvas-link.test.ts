import type {
  DeepLinkHandler,
  IDeepLinkRegistry,
} from "@posthog/platform/deep-link";
import type { IMainWindow } from "@posthog/platform/main-window";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CanvasLinkEvent, CanvasLinkService } from "./canvas-link";

function makeLogger() {
  const logger = {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
    scope: vi.fn(() => logger),
  };
  return logger;
}

function makeDeepLinkService() {
  const handlers = new Map<string, DeepLinkHandler>();
  const service = {
    registerHandler: vi.fn((key: string, handler: DeepLinkHandler) => {
      handlers.set(key, handler);
    }),
    trigger: (key: string, path: string) => {
      const handler = handlers.get(key);
      if (!handler) throw new Error(`No handler for ${key}`);
      return handler(path, new URLSearchParams());
    },
  };
  return service as unknown as IDeepLinkRegistry & {
    trigger: (key: string, path: string) => boolean;
  };
}

function makeMainWindow() {
  return {
    focus: vi.fn(),
    restore: vi.fn(),
    isMinimized: vi.fn().mockReturnValue(false),
  } as unknown as IMainWindow & {
    focus: ReturnType<typeof vi.fn>;
    restore: ReturnType<typeof vi.fn>;
    isMinimized: ReturnType<typeof vi.fn>;
  };
}

describe("CanvasLinkService", () => {
  let deepLinkService: ReturnType<typeof makeDeepLinkService>;
  let mainWindow: ReturnType<typeof makeMainWindow>;
  let service: CanvasLinkService;

  beforeEach(() => {
    deepLinkService = makeDeepLinkService();
    mainWindow = makeMainWindow();
    service = new CanvasLinkService(deepLinkService, mainWindow, makeLogger());
  });

  it("registers a 'canvas' handler on the DeepLinkService", () => {
    expect(deepLinkService.registerHandler).toHaveBeenCalledWith(
      "canvas",
      expect.any(Function),
    );
  });

  it("emits OpenCanvas with the channel and dashboard ids", () => {
    const listener = vi.fn();
    service.on(CanvasLinkEvent.OpenCanvas, listener);

    const result = deepLinkService.trigger("canvas", "chan-1/dash-2");

    expect(result).toBe(true);
    expect(listener).toHaveBeenCalledWith({
      channelId: "chan-1",
      dashboardId: "dash-2",
    });
  });

  it("decodes URL-encoded id segments", () => {
    const listener = vi.fn();
    service.on(CanvasLinkEvent.OpenCanvas, listener);

    deepLinkService.trigger("canvas", "chan%2Fa/dash%20b");

    expect(listener).toHaveBeenCalledWith({
      channelId: "chan/a",
      dashboardId: "dash b",
    });
  });

  it("queues a pending deep link when no listener is attached", () => {
    deepLinkService.trigger("canvas", "chan-1/dash-2");

    const pending = service.consumePendingDeepLink();
    expect(pending).toEqual({ channelId: "chan-1", dashboardId: "dash-2" });

    // Draining clears it
    expect(service.consumePendingDeepLink()).toBeNull();
  });

  it.each([
    ["empty path", ""],
    ["channel only (no dashboard)", "chan-1"],
  ])("returns false and does not emit for %s", (_label, path) => {
    const listener = vi.fn();
    service.on(CanvasLinkEvent.OpenCanvas, listener);

    const result = deepLinkService.trigger("canvas", path);

    expect(result).toBe(false);
    expect(listener).not.toHaveBeenCalled();
  });

  it("focuses the main window on link arrival", () => {
    deepLinkService.trigger("canvas", "chan-1/dash-2");

    expect(mainWindow.focus).toHaveBeenCalledTimes(1);
    expect(mainWindow.restore).not.toHaveBeenCalled();
  });

  it("restores the main window when it is minimized", () => {
    mainWindow.isMinimized.mockReturnValue(true);

    deepLinkService.trigger("canvas", "chan-1/dash-2");

    expect(mainWindow.restore).toHaveBeenCalledTimes(1);
    expect(mainWindow.focus).toHaveBeenCalledTimes(1);
  });
});
