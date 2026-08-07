import { LINEAR_INTEGRATION_SERVICE } from "@posthog/core/integrations/identifiers";
import type { LinearIntegrationService } from "@posthog/core/integrations/linear";
import {
  startIntegrationFlowInput,
  startIntegrationFlowOutput,
} from "@posthog/core/integrations/schemas";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";

export const linearIntegrationRouter = router({
  startFlow: publicProcedure
    .input(startIntegrationFlowInput)
    .output(startIntegrationFlowOutput)
    .mutation(({ ctx, input }) => {
      return ctx.container
        .get<LinearIntegrationService>(LINEAR_INTEGRATION_SERVICE)
        .startFlow(input.region, input.projectId);
    }),
});
