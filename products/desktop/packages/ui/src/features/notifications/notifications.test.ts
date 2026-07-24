import "reflect-metadata";
import type { NotificationTarget } from "@posthog/platform/notifications";
import { describe, expect, it, vi } from "vitest";

// Keep resolveSoundUrl real (the bus uses it to decide the native silent flag);
// only stub the side-effecting player.
vi.mock("@posthog/ui/utils/sounds", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@posthog/ui/utils/sounds")>()),
  playCompletionSound: vi.fn(),
}));

const toastMock = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
}));
vi.mock("@posthog/ui/primitives/toast", () => ({ toast: toastMock }));

import { playCompletionSound } from "@posthog/ui/utils/sounds";
import { useErrorDetailsStore } from "./errorDetails";
import type {
  IActiveView,
  INotificationSettings,
  NotificationSettings,
} from "./identifiers";
import { NotificationBus } from "./notifications";

const TASK_ID = "task-123";
const OTHER_TASK_ID = "task-999";
const taskTarget = (id: string): NotificationTarget => ({
  kind: "task",
  taskId: id,
});

function makeBus(overrides?: {
  settings?: Partial<NotificationSettings>;
  hasFocus?: boolean;
  activeTarget?: NotificationTarget;
}) {
  const notify = vi.fn();
  const showUnreadIndicator = vi.fn();
  const requestAttention = vi.fn();
  const play = vi.mocked(playCompletionSound);
  play.mockClear();
  toastMock.success.mockClear();
  toastMock.error.mockClear();
  toastMock.warning.mockClear();

  const settings: NotificationSettings = {
    desktopNotifications: true,
    dockBadgeNotifications: true,
    dockBounceNotifications: true,
    completionSound: "meep",
    completionVolume: 80,
    scaleSoundWithTaskLength: false,
    customSounds: [],
    ...overrides?.settings,
  };

  const settingsPort: INotificationSettings = { get: () => settings };
  const viewPort: IActiveView = {
    hasFocus: () => overrides?.hasFocus ?? false,
    getActiveTarget: () => overrides?.activeTarget,
  };

  const bus = new NotificationBus(
    { notify, showUnreadIndicator, requestAttention },
    settingsPort,
    viewPort,
  );

  return { bus, notify, showUnreadIndicator, requestAttention, play };
}

describe("NotificationBus tier routing (via notifyPermissionRequest)", () => {
  it("app unfocused → native notification", () => {
    const { bus, notify } = makeBus({
      hasFocus: false,
      activeTarget: taskTarget(TASK_ID),
    });
    bus.notifyPermissionRequest("My task", TASK_ID);
    expect(notify).toHaveBeenCalledTimes(1);
    expect(toastMock.warning).not.toHaveBeenCalled();
  });

  it("focused on the same task → suppressed (nothing)", () => {
    const { bus, notify, play } = makeBus({
      hasFocus: true,
      activeTarget: taskTarget(TASK_ID),
    });
    bus.notifyPermissionRequest("My task", TASK_ID);
    expect(notify).not.toHaveBeenCalled();
    expect(toastMock.warning).not.toHaveBeenCalled();
    expect(play).not.toHaveBeenCalled();
  });

  it.each([
    ["viewing a different task", taskTarget(OTHER_TASK_ID)],
    ["viewing nothing relevant", undefined],
  ])("focused, %s → in-app toast (not native)", (_label, activeTarget) => {
    const { bus, notify } = makeBus({ hasFocus: true, activeTarget });
    bus.notifyPermissionRequest("My task", TASK_ID);
    expect(notify).not.toHaveBeenCalled();
    expect(toastMock.warning).toHaveBeenCalledTimes(1);
  });
});

describe("notifyPromptComplete", () => {
  it.each([
    { stopReason: "tool_use", delivered: false },
    { stopReason: "max_tokens", delivered: false },
    { stopReason: "end_turn", delivered: true },
  ])(
    "stop reason '$stopReason' → delivered=$delivered",
    ({ stopReason, delivered }) => {
      const { bus, notify } = makeBus({ hasFocus: false });
      bus.notifyPromptComplete("My task", stopReason, TASK_ID);
      expect(notify).toHaveBeenCalledTimes(delivered ? 1 : 0);
    },
  );
});

describe("native tier settings gating (app unfocused)", () => {
  it("skips the OS notification when desktopNotifications is off, still dings dock", () => {
    const { bus, notify, showUnreadIndicator, requestAttention } = makeBus({
      hasFocus: false,
      settings: { desktopNotifications: false },
    });
    bus.notifyPermissionRequest("My task", TASK_ID);
    expect(notify).not.toHaveBeenCalled();
    expect(showUnreadIndicator).toHaveBeenCalledTimes(1);
    expect(requestAttention).toHaveBeenCalledTimes(1);
  });

  it("marks the OS notification silent when a custom sound plays", () => {
    const { bus, notify } = makeBus({
      hasFocus: false,
      settings: { completionSound: "meep" },
    });
    bus.notifyPermissionRequest("My task", TASK_ID);
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({ silent: true }),
    );
  });

  it("is not silent when completionSound is none", () => {
    const { bus, notify } = makeBus({
      hasFocus: false,
      settings: { completionSound: "none" },
    });
    bus.notifyPromptComplete("My task", "end_turn", TASK_ID);
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({ silent: false }),
    );
  });

  it("is not silent when the selected custom sound no longer exists", () => {
    // A deleted custom sound resolves to nothing, so the native chime must
    // still ring rather than the notification being silent-and-soundless.
    const { bus, notify } = makeBus({
      hasFocus: false,
      settings: { completionSound: "custom:gone", customSounds: [] },
    });
    bus.notifyPermissionRequest("My task", TASK_ID);
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({ silent: false }),
    );
  });

  it("truncates long titles in the body", () => {
    const { bus, notify } = makeBus({ hasFocus: false });
    bus.notifyPromptComplete("x".repeat(80), "end_turn", TASK_ID);
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({ body: `"${"x".repeat(50)}..." finished` }),
    );
  });
});

describe("notifyError", () => {
  const payload = { status: 500, message: "upstream exploded", body: { x: 1 } };

  it("toasts a one-line summary, never the raw payload", () => {
    const { bus } = makeBus({ hasFocus: true });
    bus.notifyError("Sync failed", payload);
    expect(toastMock.error).toHaveBeenCalledWith(
      "Sync failed",
      expect.objectContaining({ description: "upstream exploded" }),
    );
  });

  it("attaches a Details action that opens the error details dialog", () => {
    useErrorDetailsStore.getState().close();
    const { bus } = makeBus({ hasFocus: true });
    bus.notifyError("Sync failed", payload);
    const options = toastMock.error.mock.calls[0]?.[1] as {
      action?: { label: string; onClick: () => void };
    };
    expect(options.action?.label).toBe("Details");
    options.action?.onClick();
    const detail = useErrorDetailsStore.getState().detail;
    expect(detail?.title).toBe("Sync failed");
    expect(detail?.error).toBe(payload);
    useErrorDetailsStore.getState().close();
  });

  it("the Details action wins over target navigation on error toasts", () => {
    const { bus } = makeBus({ hasFocus: true });
    bus.notifyError("Sync failed", payload, taskTarget(TASK_ID));
    const options = toastMock.error.mock.calls[0]?.[1] as {
      action?: { label: string };
    };
    expect(options.action?.label).toBe("Details");
  });

  it("app unfocused → native notification with the summary as body", () => {
    const { bus, notify } = makeBus({ hasFocus: false });
    bus.notifyError("Sync failed", payload);
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Sync failed",
        body: "upstream exploded",
      }),
    );
  });
});

describe("sound", () => {
  it("plays on the toast tier too (not just native)", () => {
    const { bus, play } = makeBus({
      hasFocus: true,
      activeTarget: taskTarget(OTHER_TASK_ID),
    });
    bus.notifyPromptComplete("My task", "end_turn", TASK_ID);
    expect(play).toHaveBeenCalledTimes(1);
  });

  it.each([
    [
      "scaling off, with duration",
      false,
      (10 * 60 * 1000) as number | undefined,
      1,
    ],
    ["scaling on, quick task (<30s) → 3×", true, 10 * 1000, 3],
    ["scaling on, no duration → 1×", true, undefined, 1],
  ])("%s", (_label, scaleSoundWithTaskLength, durationMs, expectedRate) => {
    const { bus, play } = makeBus({
      hasFocus: false,
      settings: { scaleSoundWithTaskLength },
    });
    bus.notifyPromptComplete("My task", "end_turn", TASK_ID, durationMs);
    expect(play).toHaveBeenCalledWith("meep", 80, [], expectedRate);
  });
});
