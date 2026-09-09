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
    .input(customCloudSchema.nullable())
    .output(customCloudSchema.nullable())
    .mutation(({ ctx, input }) =>
      ctx.container.get<CustomCloudStore>(CUSTOM_CLOUD_STORE).set(input),
    ),
});
