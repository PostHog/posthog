import type { IDeepLinkRegistry } from "@posthog/platform/deep-link";
import type { IMainWindow } from "@posthog/platform/main-window";
import { describe, expect, it, vi } from "vitest";
import { SlackIntegrationEvent, SlackIntegrationService } from "./slack";

function makeLogger() {
  const scoped = {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  };
  return { ...scoped, scope: vi.fn(() => scoped) };
}

function createMockDeepLinkService() {
  const handlers = new Map<
    string,
    (path: string, params: URLSearchParams) => boolean
  >();
  return {
    registerHandler: vi.fn((key, handler) => handlers.set(key, handler)),
    _invoke(key: string, params: URLSearchParams) {
      const handler = handlers.get(key);
      if (!handler) throw new Error(`No handler for key: ${key}`);
      return handler("", params);
    },
  };
}

function createMockMainWindow(): IMainWindow {
  return {
    isMinimized: vi.fn(() => false),
    restore: vi.fn(),
    focus: vi.fn(),
    close: vi.fn(),
    show: vi.fn(),
    hide: vi.fn(),
    minimize: vi.fn(),
    maximize: vi.fn(),
    unmaximize: vi.fn(),
    isMaximized: vi.fn(() => false),
    isVisible: vi.fn(() => true),
    setTitle: vi.fn(),
    loadURL: vi.fn(),
    webContents: {} as never,
    on: vi.fn(),
    once: vi.fn(),
    removeListener: vi.fn(),
  } as unknown as IMainWindow;
}

function createDeps() {
  const deepLink = createMockDeepLinkService();
  const urlLauncher = { launch: vi.fn().mockResolvedValue(undefined) };
  const mainWindow = createMockMainWindow();
  const service = new SlackIntegrationService(
    deepLink as unknown as IDeepLinkRegistry,
    urlLauncher as never,
    mainWindow,
    makeLogger(),
  );
  return { service, deepLink, urlLauncher, mainWindow };
}

describe("SlackIntegrationService.startFlow", () => {
  it("launches a slack authorize URL and returns success", async () => {
    const { service, urlLauncher } = createDeps();

    const result = await service.startFlow("us", 42);

    expect(result).toEqual({ success: true });
    const launched = urlLauncher.launch.mock.calls[0][0];
    expect(launched).toContain("/api/environments/42/integrations/authorize/");
    expect(launched).toContain("kind=slack");
  });

  it("returns a failure result when launching the browser throws", async () => {
    const { service, urlLauncher } = createDeps();
    urlLauncher.launch.mockRejectedValue(new Error("no browser"));

    expect(await service.startFlow("us", 42)).toEqual({
      success: false,
      error: "no browser",
    });
  });

  it("emits FlowTimedOut after the timeout elapses", async () => {
    vi.useFakeTimers();
    try {
      const { service } = createDeps();
      const timedOut = vi.fn();
      service.on(SlackIntegrationEvent.FlowTimedOut, timedOut);

      await service.startFlow("us", 7);
      vi.advanceTimersByTime(5 * 60 * 1000);

      expect(timedOut).toHaveBeenCalledWith({ projectId: 7 });
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("SlackIntegrationService callback handling", () => {
  it("registers the slack-integration deep-link handler", () => {
    const { deepLink } = createDeps();
    expect(deepLink.registerHandler).toHaveBeenCalledWith(
      "slack-integration",
      expect.any(Function),
    );
  });

  it("parses project and integration ids on success", () => {
    const { service, deepLink } = createDeps();
    const listener = vi.fn();
    service.on(SlackIntegrationEvent.Callback, listener);

    const result = deepLink._invoke(
      "slack-integration",
      new URLSearchParams("project_id=42&integration_id=99&status=success"),
    );

    expect(result).toBe(true);
    expect(listener).toHaveBeenCalledWith({
      projectId: 42,
      integrationId: 99,
      status: "success",
      errorCode: null,
      errorMessage: null,
    });
  });

  it("treats a non-numeric integration_id as null", () => {
    const { service, deepLink } = createDeps();
    const listener = vi.fn();
    service.on(SlackIntegrationEvent.Callback, listener);

    deepLink._invoke(
      "slack-integration",
      new URLSearchParams("project_id=1&integration_id=oops"),
    );

    expect(listener).toHaveBeenCalledWith(
      expect.objectContaining({ integrationId: null }),
    );
  });

  it("captures error status with code and message", () => {
    const { service, deepLink } = createDeps();
    const listener = vi.fn();
    service.on(SlackIntegrationEvent.Callback, listener);

    deepLink._invoke(
      "slack-integration",
      new URLSearchParams("status=error&error_code=denied&error_message=nope"),
    );

    expect(listener).toHaveBeenCalledWith(
      expect.objectContaining({
        status: "error",
        errorCode: "denied",
        errorMessage: "nope",
      }),
    );
  });

  it("queues the callback when no listener exists and consumes it once", () => {
    const { service, deepLink } = createDeps();

    deepLink._invoke(
      "slack-integration",
      new URLSearchParams("project_id=5&status=success"),
    );

    expect(service.consumePendingCallback()).toEqual(
      expect.objectContaining({ projectId: 5, status: "success" }),
    );
    expect(service.consumePendingCallback()).toBeNull();
  });

  it("cancels the flow timeout so a late callback does not fire FlowTimedOut", async () => {
    vi.useFakeTimers();
    try {
      const { service, deepLink } = createDeps();
      const timedOut = vi.fn();
      service.on(SlackIntegrationEvent.FlowTimedOut, timedOut);

      await service.startFlow("us", 7);
      deepLink._invoke(
        "slack-integration",
        new URLSearchParams("project_id=7&status=success"),
      );
      vi.advanceTimersByTime(5 * 60 * 1000);

      expect(timedOut).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });
});
