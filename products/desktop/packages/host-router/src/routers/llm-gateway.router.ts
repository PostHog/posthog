import { LLM_GATEWAY_SERVICE } from "@posthog/core/llm-gateway/identifiers";
import type { LlmGatewayService } from "@posthog/core/llm-gateway/llm-gateway";
import { promptInput, promptOutput } from "@posthog/core/llm-gateway/schemas";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";

export const llmGatewayRouter = router({
  prompt: publicProcedure
    .input(promptInput)
    .output(promptOutput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<LlmGatewayService>(LLM_GATEWAY_SERVICE)
        .prompt(input.messages, {
          system: input.system,
          maxTokens: input.maxTokens,
          model: input.model,
        }),
    ),
});
