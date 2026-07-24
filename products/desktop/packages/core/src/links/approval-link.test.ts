import type {
  DeepLinkHandler,
  IDeepLinkRegistry,
} from "@posthog/platform/deep-link";
import type { IMainWindow } from "@posthog/platform/main-window";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApprovalLinkEvent,
  type ApprovalLinkPayload,
  ApprovalLinkService,
} from "./approval-link";

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

describe("ApprovalLinkService", () => {
  let deepLinkService: ReturnType<typeof makeDeepLinkService>;
  let mainWindow: ReturnType<typeof makeMainWindow>;
  let service: ApprovalLinkService;

  beforeEach(() => {
    deepLinkService = makeDeepLinkService();
    mainWindow = makeMainWindow();
    service = new ApprovalLinkService(
      deepLinkService,
      mainWindow,
      makeLogger(),
    );
  });

  it("registers an 'approval' handler on the DeepLinkService", () => {
    expect(deepLinkService.registerHandler).toHaveBeenCalledWith(
      "approval",
      expect.any(Function),
    );
  });

  it.each<{
    name: string;
    path: string;
    expected: ApprovalLinkPayload;
  }>([
    {
      name: "emits OpenApproval with the request id",
      path: "ar_abc123",
      expected: { requestId: "ar_abc123", agent: null },
    },
    {
      name: "takes only the first path segment as the request id",
      path: "ar_abc123/extra/segments",
      expected: { requestId: "ar_abc123", agent: null },
    },
    {
      name: "decodes a percent-encoded request id",
      path: "ar_abc%2D123",
      expected: { requestId: "ar_abc-123", agent: null },
    },
  ])("$name", ({ path, expected }) => {
    const listener = vi.fn();
    service.on(ApprovalLinkEvent.OpenApproval, listener);

    const result = deepLinkService.trigger("approval", path);

    expect(result).toBe(true);
    expect(listener).toHaveBeenCalledWith(expected);
  });

  it("carries the agent slug from the ?agent= query string", () => {
    const listener = vi.fn();
    service.on(ApprovalLinkEvent.OpenApproval, listener);

    const result = deepLinkService.trigger(
      "approval",
      "ar_abc123",
      "agent=my-agent",
    );

    expect(result).toBe(true);
    expect(listener).toHaveBeenCalledWith({
      requestId: "ar_abc123",
      agent: "my-agent",
    });
  });

  it("queues a pending deep link when no listener is attached", () => {
    deepLinkService.trigger("approval", "ar_xyz789");

    const pending = service.consumePendingDeepLink();
    expect(pending).toEqual({ requestId: "ar_xyz789", agent: null });

    // Draining clears it
    expect(service.consumePendingDeepLink()).toBeNull();
  });

  it("returns false and does not emit when the path is empty", () => {
    const listener = vi.fn();
    service.on(ApprovalLinkEvent.OpenApproval, listener);

    const result = deepLinkService.trigger("approval", "");

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

    deepLinkService.trigger("approval", "ar_abc123");

    expect(mainWindow.focus).toHaveBeenCalledTimes(1);
    if (expectRestore) {
      expect(mainWindow.restore).toHaveBeenCalledTimes(1);
    } else {
      expect(mainWindow.restore).not.toHaveBeenCalled();
    }
  });
});
