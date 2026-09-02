import { AGENT_SESSION_NOTIFIER } from "@posthog/core/notification/agentSessionNotifications";
import { CONTRIBUTION } from "@posthog/di/contribution";
import { ContainerModule } from "inversify";
import { ActiveTargetToastDismissal } from "./activeTargetToastDismissal.contribution";
import { AgentSessionNotificationService } from "./agentSessionNotifications";
import { NotificationBus } from "./notifications";
import { SpeechNotifier } from "./speechNotifier";

export const notificationsUiModule = new ContainerModule(({ bind }) => {
  bind(NotificationBus).toSelf().inSingletonScope();
  bind(SpeechNotifier).toSelf().inSingletonScope();
  bind(AgentSessionNotificationService).toSelf().inSingletonScope();
  bind(AGENT_SESSION_NOTIFIER).toService(AgentSessionNotificationService);
  bind(CONTRIBUTION).to(ActiveTargetToastDismissal).inSingletonScope();
});
