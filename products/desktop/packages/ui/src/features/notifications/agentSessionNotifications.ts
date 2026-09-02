import type {
  AgentSessionNotification,
  AgentSessionNotifier,
} from "@posthog/core/notification/agentSessionNotifications";
import { inject, injectable } from "inversify";
import { NotificationBus } from "./notifications";
import { SpeechNotifier } from "./speechNotifier";

@injectable()
export class AgentSessionNotificationService implements AgentSessionNotifier {
  constructor(
    @inject(NotificationBus)
    private readonly notifications: NotificationBus,
    @inject(SpeechNotifier)
    private readonly speech: SpeechNotifier,
  ) {}

  notify(notification: AgentSessionNotification): void {
    if (notification.isTaskAuthor !== true) {
      return;
    }

    if (notification.kind === "needs_input") {
      this.notifications.notifyPermissionRequest(
        notification.taskTitle,
        notification.taskId,
      );
      if (!notification.agentSpoke) {
        this.speech.speak({
          text: "needs your input",
          taskTitle: notification.taskTitle,
          taskId: notification.taskId,
          kind: "needs_input",
          source: "backstop",
          addressByName: false,
        });
      }
      return;
    }

    this.notifications.notifyPromptComplete(
      notification.taskTitle,
      notification.stopReason,
      notification.taskId,
      notification.durationMs,
    );
    if (notification.stopReason === "end_turn" && !notification.agentSpoke) {
      this.speech.speak({
        text: "finished",
        taskTitle: notification.taskTitle,
        taskId: notification.taskId,
        kind: "done",
        source: "backstop",
        addressByName: false,
      });
    }
  }
}
