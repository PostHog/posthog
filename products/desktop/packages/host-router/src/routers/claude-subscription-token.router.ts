import {
  CLAUDE_SUBSCRIPTION_TOKEN_STORE,
  type ClaudeSubscriptionTokenStore,
} from "@posthog/core/cloud-task/identifiers";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import { claudeSubscriptionTokenInput } from "@posthog/workspace-server/services/claude-subscription/schemas";

export const claudeSubscriptionTokenRouter = router({
  has: publicProcedure.query(({ ctx }) =>
    ctx.container
      .get<ClaudeSubscriptionTokenStore>(CLAUDE_SUBSCRIPTION_TOKEN_STORE)
      .has(),
  ),
  save: publicProcedure
    .input(claudeSubscriptionTokenInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ClaudeSubscriptionTokenStore>(CLAUDE_SUBSCRIPTION_TOKEN_STORE)
        .save(input.token),
    ),
  clear: publicProcedure.mutation(({ ctx }) =>
    ctx.container
      .get<ClaudeSubscriptionTokenStore>(CLAUDE_SUBSCRIPTION_TOKEN_STORE)
      .clear(),
  ),
});
