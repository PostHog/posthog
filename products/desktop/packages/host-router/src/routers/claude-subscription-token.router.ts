import {
  CLAUDE_SUBSCRIPTION_TOKEN_STORE,
  type ClaudeSubscriptionTokenStore,
} from "@posthog/core/cloud-task/identifiers";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import {
  claudeSubscriptionAccountInput,
  claudeSubscriptionTokenInput,
} from "@posthog/workspace-server/services/claude-subscription/schemas";

export const claudeSubscriptionTokenRouter = router({
  accountKey: publicProcedure.query(({ ctx }) =>
    ctx.container
      .get<ClaudeSubscriptionTokenStore>(CLAUDE_SUBSCRIPTION_TOKEN_STORE)
      .getAccountKey(),
  ),
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
        .save(input.token, input.expectedAccountKey),
    ),
  clear: publicProcedure
    .input(claudeSubscriptionAccountInput.optional())
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ClaudeSubscriptionTokenStore>(CLAUDE_SUBSCRIPTION_TOKEN_STORE)
        .clear(input?.expectedAccountKey),
    ),
});
