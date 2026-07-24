import type {
  DeepLinkHandler,
  IDeepLinkRegistry,
} from "@posthog/platform/deep-link";
import type { IMainWindow } from "@posthog/platform/main-window";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChannelLinkEvent, ChannelLinkService } from "./channel-link";

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

describe("ChannelLinkService", () => {
  let deepLinkService: ReturnType<typeof makeDeepLinkService>;
  let mainWindow: ReturnType<typeof makeMainWindow>;
  let service: ChannelLinkService;

  beforeEach(() => {
    deepLinkService = makeDeepLinkService();
    mainWindow = makeMainWindow();
    service = new ChannelLinkService(deepLinkService, mainWindow, makeLogger());
  });

  it("registers a 'channel' handler on the DeepLinkService", () => {
    expect(deepLinkService.registerHandler).toHaveBeenCalledWith(
      "channel",
      expect.any(Function),
    );
  });

  it("emits OpenChannel with just the channel id", () => {
    const listener = vi.fn();
    service.on(ChannelLinkEvent.OpenChannel, listener);

    const result = deepLinkService.trigger("channel", "chan-1");

    expect(result).toBe(true);
    expect(listener).toHaveBeenCalledWith({ channelId: "chan-1" });
  });

  it("emits OpenChannel with a thread task id", () => {
    const listener = vi.fn();
    service.on(ChannelLinkEvent.OpenChannel, listener);

    const result = deepLinkService.trigger("channel", "chan-1/tasks/task-2");

    expect(result).toBe(true);
    expect(listener).toHaveBeenCalledWith({
      channelId: "chan-1",
      taskId: "task-2",
    });
  });

  it("decodes URL-encoded id segments", () => {
    const listener = vi.fn();
    service.on(ChannelLinkEvent.OpenChannel, listener);

    deepLinkService.trigger("channel", "chan%2Fa/tasks/task%20b");

    expect(listener).toHaveBeenCalledWith({
      channelId: "chan/a",
      taskId: "task b",
    });
  });

  it("queues a pending deep link when no listener is attached", () => {
    deepLinkService.trigger("channel", "chan-1/tasks/task-2");

    const pending = service.consumePendingDeepLink();
    expect(pending).toEqual({ channelId: "chan-1", taskId: "task-2" });

    // Draining clears it
    expect(service.consumePendingDeepLink()).toBeNull();
  });

  it.each([
    ["empty path", ""],
    ["unknown sub-path", "chan-1/dashboards/dash-2"],
    ["tasks without a task id", "chan-1/tasks"],
    ["trailing segments after the task id", "chan-1/tasks/task-2/extra"],
  ])("returns false and does not emit for %s", (_label, path) => {
    const listener = vi.fn();
    service.on(ChannelLinkEvent.OpenChannel, listener);

    const result = deepLinkService.trigger("channel", path);

    expect(result).toBe(false);
    expect(listener).not.toHaveBeenCalled();
  });

  it("focuses the main window on link arrival", () => {
    deepLinkService.trigger("channel", "chan-1");

    expect(mainWindow.focus).toHaveBeenCalledTimes(1);
    expect(mainWindow.restore).not.toHaveBeenCalled();
  });

  it("restores the main window when it is minimized", () => {
    mainWindow.isMinimized.mockReturnValue(true);

    deepLinkService.trigger("channel", "chan-1");

    expect(mainWindow.restore).toHaveBeenCalledTimes(1);
    expect(mainWindow.focus).toHaveBeenCalledTimes(1);
  });
});
