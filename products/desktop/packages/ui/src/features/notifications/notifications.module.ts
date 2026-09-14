import { AGENT_SESSION_NOTIFIER } from "@posthog/core/notification/agentSessionNotifications";
import { ContainerModule } from "inversify";
import { AgentSessionNotificationService } from "./agentSessionNotifications";
import { NotificationBus } from "./notifications";
import { SpeechNotifier } from "./speechNotifier";

export const notificationsUiModule = new ContainerModule(({ bind }) => {
  bind(NotificationBus).toSelf().inSingletonScope();
  bind(SpeechNotifier).toSelf().inSingletonScope();
  bind(AgentSessionNotificationService).toSelf().inSingletonScope();
  bind(AGENT_SESSION_NOTIFIER).toService(AgentSessionNotificationService);
});
