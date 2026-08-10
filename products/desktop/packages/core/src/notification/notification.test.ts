import type { INotifier, NotifyOptions } from "@posthog/platform/notifier";
import { describe, expect, it, vi } from "vitest";
import { NotificationService } from "./notification";

function makeLogger() {
  const scoped = {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  };
  return { ...scoped, scope: vi.fn(() => scoped) };
}

function createDeps(supported = true) {
  let lastNotify: NotifyOptions | undefined;
  let focusHandler: (() => void) | undefined;

  const notifier: INotifier = {
    isSupported: vi.fn(() => supported),
    notify: vi.fn((options: NotifyOptions) => {
      lastNotify = options;
    }),
    setUnreadIndicator: vi.fn(),
    requestAttention: vi.fn(),
  };

  const mainWindow = {
    onFocus: vi.fn((handler: () => void) => {
      focusHandler = handler;
    }),
    isMinimized: vi.fn(() => false),
    restore: vi.fn(),
    focus: vi.fn(),
  };

  const openTargetLink = { open: vi.fn() };

  const service = new NotificationService(
    openTargetLink as never,
    notifier,
    mainWindow as never,
    makeLogger(),
  );

  return {
    service,
    notifier,
    mainWindow,
    openTargetLink,
    getLastNotify: () => lastNotify,
    getFocusHandler: () => focusHandler,
  };
}

describe("NotificationService.send", () => {
  it("does not notify when the platform is unsupported", () => {
    const { service, notifier } = createDeps(false);
    service.send("t", "b", false);
    expect(notifier.notify).not.toHaveBeenCalled();
  });

  it("forwards title, body and silent to the notifier", () => {
    const { service, getLastNotify } = createDeps();
    service.send("Title", "Body", true);
    expect(getLastNotify()).toMatchObject({
      title: "Title",
      body: "Body",
      silent: true,
    });
  });

  it("focuses the window when the notification is clicked", () => {
    const { service, mainWindow, getLastNotify } = createDeps();
    mainWindow.isMinimized.mockReturnValue(true);

    service.send("Title", "Body", false);
    getLastNotify()?.onClick?.();

    expect(mainWindow.restore).toHaveBeenCalled();
    expect(mainWindow.focus).toHaveBeenCalled();
  });

  it("opens the target on click when one is provided", () => {
    const { service, openTargetLink, getLastNotify } = createDeps();

    const target = { kind: "task" as const, taskId: "task-9" };
    service.send("Title", "Body", false, target);
    getLastNotify()?.onClick?.();

    expect(openTargetLink.open).toHaveBeenCalledWith(target);
  });

  it("does not open a target on click when none is provided", () => {
    const { service, openTargetLink, getLastNotify } = createDeps();

    service.send("Title", "Body", false);
    getLastNotify()?.onClick?.();

    expect(openTargetLink.open).not.toHaveBeenCalled();
  });
});

describe("NotificationService dock badge", () => {
  it("sets the unread indicator once and is idempotent", () => {
    const { service, notifier } = createDeps();

    service.showDockBadge();
    service.showDockBadge();

    expect(notifier.setUnreadIndicator).toHaveBeenCalledTimes(1);
    expect(notifier.setUnreadIndicator).toHaveBeenCalledWith(true);
  });

  it("clears the badge on window focus only when a badge is set", () => {
    const { service, notifier, getFocusHandler } = createDeps();
    service.init();

    getFocusHandler()?.();
    expect(notifier.setUnreadIndicator).not.toHaveBeenCalled();

    service.showDockBadge();
    vi.mocked(notifier.setUnreadIndicator).mockClear();

    getFocusHandler()?.();
    expect(notifier.setUnreadIndicator).toHaveBeenCalledWith(false);
  });

  it("requests attention when bouncing the dock", () => {
    const { service, notifier } = createDeps();
    service.bounceDock();
    expect(notifier.requestAttention).toHaveBeenCalled();
  });
});
