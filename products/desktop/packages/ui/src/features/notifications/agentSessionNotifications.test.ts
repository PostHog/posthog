import { describe, expect, it, vi } from "vitest";
import { AgentSessionNotificationService } from "./agentSessionNotifications";
import type { NotificationBus } from "./notifications";
import type { SpeechNotifier } from "./speechNotifier";

function createService() {
  const notifications = {
    notifyPermissionRequest: vi.fn(),
    notifyPromptComplete: vi.fn(),
  } as unknown as NotificationBus;
  const speech = { speak: vi.fn() } as unknown as SpeechNotifier;
  const service = new AgentSessionNotificationService(notifications, speech);
  return { notifications, service, speech };
}

describe("AgentSessionNotificationService", () => {
  it("routes a completed turn through the shared notification channels", () => {
    const { notifications, service, speech } = createService();

    service.notify({
      kind: "turn_completed",
      taskId: "task-1",
      taskTitle: "Fix notifications",
      stopReason: "end_turn",
      durationMs: 42_000,
      isTaskAuthor: true,
    });

    expect(notifications.notifyPromptComplete).toHaveBeenCalledWith(
      "Fix notifications",
      "end_turn",
      "task-1",
      42_000,
    );
    expect(speech.speak).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "done",
        source: "backstop",
        taskId: "task-1",
      }),
    );
  });

  it("routes input requests without repeating agent narration", () => {
    const { notifications, service, speech } = createService();

    service.notify({
      kind: "needs_input",
      taskId: "task-1",
      taskTitle: "Fix notifications",
      isTaskAuthor: true,
      agentSpoke: true,
    });

    expect(notifications.notifyPermissionRequest).toHaveBeenCalledWith(
      "Fix notifications",
      "task-1",
    );
    expect(speech.speak).not.toHaveBeenCalled();
  });

  it.each([false, undefined])(
    "does not notify when task ownership is %s",
    (isTaskAuthor) => {
      const { notifications, service, speech } = createService();

      service.notify({
        kind: "turn_completed",
        taskId: "task-1",
        taskTitle: "Fix notifications",
        stopReason: "end_turn",
        isTaskAuthor,
      });

      expect(notifications.notifyPromptComplete).not.toHaveBeenCalled();
      expect(speech.speak).not.toHaveBeenCalled();
    },
  );
});
