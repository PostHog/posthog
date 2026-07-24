import { ContainerModule } from "inversify";
import { NotificationBus } from "./notifications";
import { SpeechNotifier } from "./speechNotifier";

export const notificationsUiModule = new ContainerModule(({ bind }) => {
  bind(NotificationBus).toSelf().inSingletonScope();
  bind(SpeechNotifier).toSelf().inSingletonScope();
});
