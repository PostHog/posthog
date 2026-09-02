import type {
  DeepLinkHandler,
  IDeepLinkRegistry,
} from "@posthog/platform/deep-link";
import type { IMainWindow } from "@posthog/platform/main-window";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ScoutLinkEvent,
  type ScoutLinkPayload,
  ScoutLinkService,
} from "./scout-link";

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

describe("ScoutLinkService", () => {
  let deepLinkService: ReturnType<typeof makeDeepLinkService>;
  let mainWindow: ReturnType<typeof makeMainWindow>;
  let service: ScoutLinkService;

  beforeEach(() => {
    deepLinkService = makeDeepLinkService();
    mainWindow = makeMainWindow();
    service = new ScoutLinkService(deepLinkService, mainWindow, makeLogger());
  });

  it("registers a 'scout' handler on the DeepLinkService", () => {
    expect(deepLinkService.registerHandler).toHaveBeenCalledWith(
      "scout",
      expect.any(Function),
    );
  });

  it.each<{
    name: string;
    path: string;
    search: string;
    expected: ScoutLinkPayload;
  }>([
    {
      name: "emits OpenScout with the finding id from the query param",
      path: "error-tracking",
      search: "finding=abc-123",
      expected: { skillSlug: "error-tracking", findingId: "abc-123" },
    },
    {
      name: "emits OpenScout without a finding id when none is supplied",
      path: "error-tracking",
      search: "",
      expected: { skillSlug: "error-tracking", findingId: undefined },
    },
    {
      name: "takes only the first path segment as the skill slug",
      path: "error-tracking/extra/segments",
      search: "",
      expected: { skillSlug: "error-tracking", findingId: undefined },
    },
    {
      name: "decodes a percent-encoded skill slug",
      path: "error%2Dtracking",
      search: "",
      expected: { skillSlug: "error-tracking", findingId: undefined },
    },
  ])("$name", ({ path, search, expected }) => {
    const listener = vi.fn();
    service.on(ScoutLinkEvent.OpenScout, listener);

    const result = deepLinkService.trigger("scout", path, search);

    expect(result).toBe(true);
    expect(listener).toHaveBeenCalledWith(expected);
  });

  it("queues a pending deep link when no listener is attached", () => {
    deepLinkService.trigger("scout", "web-analytics", "finding=f-1");

    const pending = service.consumePendingDeepLink();
    expect(pending).toEqual({ skillSlug: "web-analytics", findingId: "f-1" });

    // Draining clears it
    expect(service.consumePendingDeepLink()).toBeNull();
  });

  it("returns false and does not emit when the path is empty", () => {
    const listener = vi.fn();
    service.on(ScoutLinkEvent.OpenScout, listener);

    const result = deepLinkService.trigger("scout", "");

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

    deepLinkService.trigger("scout", "error-tracking");

    expect(mainWindow.focus).toHaveBeenCalledTimes(1);
    if (expectRestore) {
      expect(mainWindow.restore).toHaveBeenCalledTimes(1);
    } else {
      expect(mainWindow.restore).not.toHaveBeenCalled();
    }
  });
});
