import { ContainerModule } from "inversify";
import { LLM_GATEWAY_SERVICE } from "./identifiers";
import { LlmGatewayService } from "./llm-gateway";

export const llmGatewayModule = new ContainerModule(({ bind }) => {
  bind(LLM_GATEWAY_SERVICE).to(LlmGatewayService).inSingletonScope();
});
