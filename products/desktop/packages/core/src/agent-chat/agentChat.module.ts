import { ContainerModule } from "inversify";
import { AgentChatService } from "./agentChatService";
import { AGENT_CHAT_SERVICE } from "./identifiers";

export const agentChatCoreModule = new ContainerModule(({ bind }) => {
  bind(AgentChatService).toSelf().inSingletonScope();
  bind(AGENT_CHAT_SERVICE).toService(AgentChatService);
});
