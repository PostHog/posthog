import {
  type FlowTimedOut,
  GitHubIntegrationEvent,
  type GitHubIntegrationService,
  type IntegrationCallback,
} from "@posthog/core/integrations/github";
import { GITHUB_INTEGRATION_SERVICE } from "@posthog/core/integrations/identifiers";
import {
  startIntegrationFlowInput,
  startIntegrationFlowOutput,
} from "@posthog/core/integrations/schemas";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";

export const githubIntegrationRouter = router({
  startFlow: publicProcedure
    .input(startIntegrationFlowInput)
    .output(startIntegrationFlowOutput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<GitHubIntegrationService>(GITHUB_INTEGRATION_SERVICE)
        .startFlow(input.region, input.projectId),
    ),

  onCallback: publicProcedure.subscription(async function* (opts) {
    const service = opts.ctx.container.get<GitHubIntegrationService>(
      GITHUB_INTEGRATION_SERVICE,
    );
    const iterable = service.toIterable(GitHubIntegrationEvent.Callback, {
      signal: opts.signal,
    });
    for await (const data of iterable) {
      yield data;
    }
  }),

  onFlowTimedOut: publicProcedure.subscription(async function* (opts) {
    const service = opts.ctx.container.get<GitHubIntegrationService>(
      GITHUB_INTEGRATION_SERVICE,
    );
    const iterable = service.toIterable(GitHubIntegrationEvent.FlowTimedOut, {
      signal: opts.signal,
    });
    for await (const data of iterable) {
      yield data;
    }
  }),

  consumePendingCallback: publicProcedure.query(
    ({ ctx }): IntegrationCallback | null =>
      ctx.container
        .get<GitHubIntegrationService>(GITHUB_INTEGRATION_SERVICE)
        .consumePendingCallback(),
  ),
});

export type { IntegrationCallback, FlowTimedOut };
