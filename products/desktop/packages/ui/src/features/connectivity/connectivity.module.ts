import { CONTRIBUTION } from "@posthog/di/contribution";
import { ContainerModule } from "inversify";
import { ConnectivityEventsContribution } from "./connectivity-events.contribution";
import { NetworkReconnectContribution } from "./network-reconnect.contribution";

export const connectivityUiModule = new ContainerModule(({ bind }) => {
  bind(CONTRIBUTION).to(ConnectivityEventsContribution).inSingletonScope();
  bind(CONTRIBUTION).to(NetworkReconnectContribution).inSingletonScope();
});
