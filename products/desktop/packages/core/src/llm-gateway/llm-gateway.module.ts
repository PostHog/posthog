import { ContainerModule } from "inversify";
import { GatewayTokenService } from "./gateway-token";
import { GATEWAY_TOKEN_SERVICE, LLM_GATEWAY_SERVICE } from "./identifiers";
import { LlmGatewayService } from "./llm-gateway";

export const llmGatewayModule = new ContainerModule(({ bind }) => {
  bind(GATEWAY_TOKEN_SERVICE).to(GatewayTokenService).inSingletonScope();
  bind(LLM_GATEWAY_SERVICE).to(LlmGatewayService).inSingletonScope();
});
