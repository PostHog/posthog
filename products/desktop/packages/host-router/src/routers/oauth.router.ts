import { OAUTH_SERVICE } from "@posthog/core/oauth/identifiers";
import type { OAuthService } from "@posthog/core/oauth/oauth";
import { cancelFlowOutput } from "@posthog/core/oauth/schemas";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";

export const oauthRouter = router({
  cancelFlow: publicProcedure
    .output(cancelFlowOutput)
    .mutation(({ ctx }) =>
      ctx.container.get<OAuthService>(OAUTH_SERVICE).cancelFlow(),
    ),
});
