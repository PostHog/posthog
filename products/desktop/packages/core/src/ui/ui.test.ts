import type { IDeepLinkRegistry } from "@posthog/platform/deep-link";
import type { IMainWindow } from "@posthog/platform/main-window";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { UiAuth } from "./ports";
import { UIServiceEvent } from "./schemas";
import { UIService } from "./ui";

function makeAuth(): UiAuth {
  return { invalidateAccessTokenForTest: vi.fn().mockResolvedValue(undefined) };
}

function makeDeepLink(): IDeepLinkRegistry {
  return {
    registerHandler: vi.fn(),
    unregisterHandler: vi.fn(),
  } as unknown as IDeepLinkRegistry;
}

function makeMainWindow(): IMainWindow {
  return {
    isMinimized: vi.fn().mockReturnValue(false),
    focus: vi.fn(),
    restore: vi.fn(),
  } as unknown as IMainWindow;
}

function makeService(): UIService {
  return new UIService(makeAuth(), makeDeepLink(), makeMainWindow());
}

describe("UIService signal events", () => {
  it.each([
    ["newTask", UIServiceEvent.NewTask],
    ["resetLayout", UIServiceEvent.ResetLayout],
    ["clearStorage", UIServiceEvent.ClearStorage],
  ] as const)("%s emits %s", (method, event) => {
    const service = makeService();
    const listener = vi.fn();
    service.on(event, listener);

    (service[method] as () => void)();

    expect(listener).toHaveBeenCalledWith(true);
  });

  it("openSettings emits the category, defaulting to plan-usage", () => {
    const service = makeService();
    const listener = vi.fn();
    service.on(UIServiceEvent.OpenSettings, listener);

    service.openSettings();

    expect(listener).toHaveBeenCalledWith({ category: "plan-usage" });
  });

  it("openSettings forwards a custom category", () => {
    const service = makeService();
    const listener = vi.fn();
    service.on(UIServiceEvent.OpenSettings, listener);

    service.openSettings("agents");

    expect(listener).toHaveBeenCalledWith({ category: "agents" });
  });
});

describe("UIService usage deep link", () => {
  let deepLink: IDeepLinkRegistry;
  let mainWindow: IMainWindow;
  let service: UIService;

  beforeEach(() => {
    deepLink = makeDeepLink();
    mainWindow = makeMainWindow();
    service = new UIService(makeAuth(), deepLink, mainWindow);
  });

  function handler(): (path: string) => boolean {
    return (deepLink.registerHandler as ReturnType<typeof vi.fn>).mock
      .calls[0][1] as (path: string) => boolean;
  }

  it("registers a usage handler", () => {
    expect(deepLink.registerHandler).toHaveBeenCalledWith(
      "usage",
      expect.any(Function),
    );
  });

  it("defaults an empty path to plan-usage", () => {
    const listener = vi.fn();
    service.on(UIServiceEvent.OpenSettings, listener);

    expect(handler()("")).toBe(true);
    expect(listener).toHaveBeenCalledWith({ category: "plan-usage" });
  });

  it("takes the first segment as the category", () => {
    const listener = vi.fn();
    service.on(UIServiceEvent.OpenSettings, listener);

    expect(handler()("agents")).toBe(true);
    expect(listener).toHaveBeenCalledWith({ category: "agents" });
  });

  it("ignores extra path segments", () => {
    const listener = vi.fn();
    service.on(UIServiceEvent.OpenSettings, listener);

    handler()("agents/foo");
    expect(listener).toHaveBeenCalledWith({ category: "agents" });
  });

  it("percent-decodes the category", () => {
    const listener = vi.fn();
    service.on(UIServiceEvent.OpenSettings, listener);

    handler()("plan%20usage");
    expect(listener).toHaveBeenCalledWith({ category: "plan usage" });
  });

  it("queues the link when no renderer is listening", () => {
    expect(handler()("agents")).toBe(true);

    expect(service.consumePendingSettingsLink()).toEqual({
      category: "agents",
    });
  });

  it("emits instead of queueing when a listener is attached", () => {
    const listener = vi.fn();
    service.on(UIServiceEvent.OpenSettings, listener);

    handler()("agents");
    expect(service.consumePendingSettingsLink()).toBeNull();
  });

  it("drains the pending link once", () => {
    handler()("agents");
    expect(service.consumePendingSettingsLink()).toEqual({
      category: "agents",
    });
    expect(service.consumePendingSettingsLink()).toBeNull();
  });

  it("focuses and restores the window", () => {
    (mainWindow.isMinimized as ReturnType<typeof vi.fn>).mockReturnValue(true);
    service.on(UIServiceEvent.OpenSettings, vi.fn());

    handler()("");
    expect(mainWindow.restore).toHaveBeenCalledTimes(1);
    expect(mainWindow.focus).toHaveBeenCalledTimes(1);
  });
});

describe("UIService.invalidateToken", () => {
  it("invalidates the access token before emitting the signal", async () => {
    const auth = makeAuth();
    const service = new UIService(auth, makeDeepLink(), makeMainWindow());
    const listener = vi.fn();
    service.on(UIServiceEvent.InvalidateToken, listener);

    await service.invalidateToken();

    expect(auth.invalidateAccessTokenForTest).toHaveBeenCalledTimes(1);
    expect(listener).toHaveBeenCalledWith(true);
  });
});
