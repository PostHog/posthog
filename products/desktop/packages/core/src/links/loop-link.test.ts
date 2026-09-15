import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  makeDeepLinkService,
  makeLogger,
  makeMainWindow,
} from "./link-test-helpers";
import {
  LoopLinkEvent,
  type LoopLinkPayload,
  LoopLinkService,
} from "./loop-link";

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
