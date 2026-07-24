import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import type { ISecureStoreService } from "@posthog/workspace-server/services/secure-store/identifiers";
import { SECURE_STORE_SERVICE } from "@posthog/workspace-server/services/secure-store/identifiers";
import {
  secureStoreGetInput,
  secureStoreRemoveInput,
  secureStoreSetInput,
} from "@posthog/workspace-server/services/secure-store/schemas";

export const secureStoreRouter = router({
  getItem: publicProcedure
    .input(secureStoreGetInput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<ISecureStoreService>(SECURE_STORE_SERVICE)
        .getItem(input.key),
    ),

  setItem: publicProcedure
    .input(secureStoreSetInput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<ISecureStoreService>(SECURE_STORE_SERVICE)
        .setItem(input.key, input.value),
    ),

  removeItem: publicProcedure
    .input(secureStoreRemoveInput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<ISecureStoreService>(SECURE_STORE_SERVICE)
        .removeItem(input.key),
    ),

  clear: publicProcedure.query(({ ctx }) =>
    ctx.container.get<ISecureStoreService>(SECURE_STORE_SERVICE).clear(),
  ),
});
