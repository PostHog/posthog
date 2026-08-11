import type {
  DeepLinkHandler,
  IDeepLinkRegistry,
} from "@posthog/platform/deep-link";
import type { IMainWindow } from "@posthog/platform/main-window";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  LoopLinkEvent,
  type LoopLinkPayload,
  LoopLinkService,
} from "./loop-link";

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
    trigger: (key: string, path: string, search = "") => {
      const handler = handlers.get(key);
      if (!handler) throw new Error(`No handler for ${key}`);
      return handler(path, new URLSearchParams(search));
    },
  };
  return service as unknown as IDeepLinkRegistry & {
    trigger: (key: string, path: string, search?: string) => boolean;
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

describe("LoopLinkService", () => {
  let deepLinkService: ReturnType<typeof makeDeepLinkService>;
  let mainWindow: ReturnType<typeof makeMainWindow>;
  let service: LoopLinkService;

  beforeEach(() => {
    deepLinkService = makeDeepLinkService();
    mainWindow = makeMainWindow();
    service = new LoopLinkService(deepLinkService, mainWindow, makeLogger());
  });

  it("registers a 'loop' handler on the DeepLinkService", () => {
    expect(deepLinkService.registerHandler).toHaveBeenCalledWith(
      "loop",
      expect.any(Function),
    );
  });

  it.each<{ name: string; path: string; expected: LoopLinkPayload }>([
    {
      name: "emits OpenLoop with the loop id",
      path: "loop-abc-123",
      expected: { loopId: "loop-abc-123" },
    },
    {
      name: "takes only the first path segment as the loop id",
      path: "loop-abc-123/extra/segments",
      expected: { loopId: "loop-abc-123" },
    },
    {
      name: "decodes a percent-encoded loop id",
      path: "loop%2Dabc",
      expected: { loopId: "loop-abc" },
    },
  ])("$name", ({ path, expected }) => {
    const listener = vi.fn();
    service.on(LoopLinkEvent.OpenLoop, listener);

    const result = deepLinkService.trigger("loop", path);

    expect(result).toBe(true);
    expect(listener).toHaveBeenCalledWith(expected);
  });

  it("queues a pending deep link when no listener is attached", () => {
    deepLinkService.trigger("loop", "loop-abc-123");

    const pending = service.consumePendingDeepLink();
    expect(pending).toEqual({ loopId: "loop-abc-123" });

    // Draining clears it
    expect(service.consumePendingDeepLink()).toBeNull();
  });

  it("returns false and does not emit when the path is empty", () => {
    const listener = vi.fn();
    service.on(LoopLinkEvent.OpenLoop, listener);

    const result = deepLinkService.trigger("loop", "");

    expect(result).toBe(false);
    expect(listener).not.toHaveBeenCalled();
  });

  it.each<{ name: string; minimized: boolean; expectRestore: boolean }>([
    {
      name: "focuses the main window on link arrival",
      minimized: false,
      expectRestore: false,
    },
    {
      name: "restores then focuses the main window when it is minimized",
      minimized: true,
      expectRestore: true,
    },
  ])("$name", ({ minimized, expectRestore }) => {
    mainWindow.isMinimized.mockReturnValue(minimized);

    deepLinkService.trigger("loop", "loop-abc-123");

    expect(mainWindow.focus).toHaveBeenCalledTimes(1);
    if (expectRestore) {
      expect(mainWindow.restore).toHaveBeenCalledTimes(1);
    } else {
      expect(mainWindow.restore).not.toHaveBeenCalled();
    }
  });
});
