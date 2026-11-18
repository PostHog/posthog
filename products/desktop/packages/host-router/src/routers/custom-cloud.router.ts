import type { AuthService } from "@posthog/core/auth/auth";
import { AUTH_SERVICE } from "@posthog/core/auth/auth.module";
import {
  CUSTOM_CLOUD_STORE,
  type CustomCloudStore,
} from "@posthog/core/custom-cloud/identifiers";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import { customCloudSchema } from "@posthog/shared";

export const customCloudRouter = router({
  get: publicProcedure
    .output(customCloudSchema.nullable())
    .query(({ ctx }) =>
      ctx.container.get<CustomCloudStore>(CUSTOM_CLOUD_STORE).get(),
    ),

  set: publicProcedure
    .input(customCloudSchema)
    .output(customCloudSchema.nullable())
    .mutation(async ({ ctx, input }) => {
      const store = ctx.container.get<CustomCloudStore>(CUSTOM_CLOUD_STORE);
      const auth = ctx.container.get<AuthService>(AUTH_SERVICE);
      const previous = store.get();
      const session = auth.getState();
      // A session holds a refresh token that only the instance that issued it
      // accepts. Sending it to another instance is what this logout prevents.
      const movesTarget =
        session.cloudRegion === "custom" &&
        previous?.url !== undefined &&
        previous.url !== input.url;
      if (movesTarget) {
        await auth.logout();
      }
      return store.set(input);
    }),
});
