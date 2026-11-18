import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import {
  DISK_CACHE_SERVICE,
  type IDiskCache,
} from "@posthog/platform/disk-cache";

export const diskCacheRouter = router({
  clear: publicProcedure.mutation(({ ctx }) =>
    ctx.container.get<IDiskCache>(DISK_CACHE_SERVICE).clear(),
  ),
});
