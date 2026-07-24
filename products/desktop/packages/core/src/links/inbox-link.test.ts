import type {
  DeepLinkHandler,
  IDeepLinkRegistry,
} from "@posthog/platform/deep-link";
import type { IMainWindow } from "@posthog/platform/main-window";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { InboxLinkEvent, InboxLinkService } from "./inbox-link";

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

describe("InboxLinkService", () => {
  let deepLinkService: ReturnType<typeof makeDeepLinkService>;
  let mainWindow: ReturnType<typeof makeMainWindow>;
  let service: InboxLinkService;

  beforeEach(() => {
    deepLinkService = makeDeepLinkService();
    mainWindow = makeMainWindow();
    service = new InboxLinkService(deepLinkService, mainWindow, makeLogger());
  });

  it("registers an 'inbox' handler on the DeepLinkService", () => {
    expect(deepLinkService.registerHandler).toHaveBeenCalledWith(
      "inbox",
      expect.any(Function),
    );
  });

  it("emits OpenReport when a listener is attached", () => {
    const listener = vi.fn();
    service.on(InboxLinkEvent.OpenReport, listener);

    const result = deepLinkService.trigger("inbox", "abc-123");

    expect(result).toBe(true);
    expect(listener).toHaveBeenCalledWith({ reportId: "abc-123" });
  });

  it("queues a pending deep link when no listener is attached", () => {
    deepLinkService.trigger("inbox", "pending-id");

    const pending = service.consumePendingDeepLink();
    expect(pending).toEqual({ reportId: "pending-id" });

    // Draining clears it
    expect(service.consumePendingDeepLink()).toBeNull();
  });

  it("takes only the first path segment as the report id", () => {
    const listener = vi.fn();
    service.on(InboxLinkEvent.OpenReport, listener);

    deepLinkService.trigger("inbox", "abc-123/extra/segments");

    expect(listener).toHaveBeenCalledWith({ reportId: "abc-123" });
  });

  it("ignores a trailing slug segment after the report id", () => {
    const listener = vi.fn();
    service.on(InboxLinkEvent.OpenReport, listener);

    deepLinkService.trigger("inbox", "abc-123/fix-inbox--Add-foo");

    expect(listener).toHaveBeenCalledWith({ reportId: "abc-123" });
  });

  it("returns false and does not emit when the path is empty", () => {
    const listener = vi.fn();
    service.on(InboxLinkEvent.OpenReport, listener);

    const result = deepLinkService.trigger("inbox", "");

    expect(result).toBe(false);
    expect(listener).not.toHaveBeenCalled();
  });

  it("focuses the main window on link arrival", () => {
    deepLinkService.trigger("inbox", "abc-123");

    expect(mainWindow.focus).toHaveBeenCalledTimes(1);
    expect(mainWindow.restore).not.toHaveBeenCalled();
  });

  it("restores the main window when it is minimized", () => {
    mainWindow.isMinimized.mockReturnValue(true);

    deepLinkService.trigger("inbox", "abc-123");

    expect(mainWindow.restore).toHaveBeenCalledTimes(1);
    expect(mainWindow.focus).toHaveBeenCalledTimes(1);
  });
});
