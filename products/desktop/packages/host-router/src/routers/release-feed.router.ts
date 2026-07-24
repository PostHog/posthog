import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import { RELEASE_FEED_SERVICE } from "@posthog/workspace-server/services/release-feed/identifiers";
import type { ReleaseFeedService } from "@posthog/workspace-server/services/release-feed/release-feed";
import {
  listReleasesInput,
  listReleasesOutput,
} from "@posthog/workspace-server/services/release-feed/schemas";

export const releaseFeedRouter = router({
  list: publicProcedure
    .input(listReleasesInput)
    .output(listReleasesOutput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<ReleaseFeedService>(RELEASE_FEED_SERVICE)
        .listReleases(input?.expectVersion),
    ),
});
