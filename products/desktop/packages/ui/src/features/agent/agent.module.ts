import { CONTRIBUTION } from "@posthog/di/contribution";
import { ContainerModule } from "inversify";
import { AgentEventsContribution } from "./agent-events.contribution";

export const agentUiModule = new ContainerModule(({ bind }) => {
  bind(CONTRIBUTION).to(AgentEventsContribution).inSingletonScope();
});
