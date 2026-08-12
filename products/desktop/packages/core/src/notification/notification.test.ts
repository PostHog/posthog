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
    setUnreadCount: vi.fn(),
    clearAttention: vi.fn(),
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
  it("forwards a changed count and drops a repeat of the same one", () => {
    const { service, notifier } = createDeps();

    service.setUnreadCount(3);
    service.setUnreadCount(3);
    service.setUnreadCount(0);

    expect(notifier.setUnreadCount).toHaveBeenCalledTimes(2);
    expect(notifier.setUnreadCount).toHaveBeenNthCalledWith(1, 3);
    expect(notifier.setUnreadCount).toHaveBeenNthCalledWith(2, 0);
  });

  it.each([
    ["negative", -1, 0],
    ["non-finite", Number.NaN, 0],
    ["fractional", 2.7, 2],
  ])("coerces a %s count", (_label, input, expected) => {
    const { service, notifier } = createDeps();

    service.setUnreadCount(input);

    expect(notifier.setUnreadCount).toHaveBeenCalledWith(expected);
  });

  it("stops the attention flash on focus without changing the count", () => {
    const { service, notifier, getFocusHandler } = createDeps();
    service.init();
    service.setUnreadCount(3);

    getFocusHandler()?.();

    expect(notifier.clearAttention).toHaveBeenCalled();
    expect(notifier.setUnreadCount).toHaveBeenCalledTimes(1);
    expect(notifier.setUnreadCount).toHaveBeenCalledWith(3);
  });

  it("requests attention when bouncing the dock", () => {
    const { service, notifier } = createDeps();
    service.bounceDock();
    expect(notifier.requestAttention).toHaveBeenCalled();
  });
});
