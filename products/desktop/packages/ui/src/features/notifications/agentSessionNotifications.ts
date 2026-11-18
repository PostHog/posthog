import type {
  AgentSessionNotification,
  AgentSessionNotifier,
} from "@posthog/core/notification/agentSessionNotifications";
import { logger } from "@posthog/ui/shell/logger";
import { inject, injectable } from "inversify";
import { NotificationBus } from "./notifications";
import { SpeechNotifier } from "./speechNotifier";

const log = logger.scope("notifications");

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
      log.debug("Agent session notification dropped, not the task author", {
        kind: notification.kind,
        trigger: notification.trigger,
        taskId: notification.taskId,
        taskRunId: notification.taskRunId,
      });
      return;
    }

    // Everything the session knew about the trigger rides along, so the
    // notification log names the exact path that rang.
    const debug = {
      trigger: notification.trigger,
      taskRunId: notification.taskRunId,
      agentSpoke: notification.agentSpoke === true,
    };

    if (notification.kind === "needs_input") {
      this.notifications.notifyPermissionRequest(
        notification.taskTitle,
        notification.taskId,
        debug,
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
      debug,
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
