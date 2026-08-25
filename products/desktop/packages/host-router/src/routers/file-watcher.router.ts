import type { ServiceResolver } from "@posthog/host-trpc/context";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import { z } from "zod";
import {
  FILE_WATCHER_CONTROL,
  type HostFileWatcherControl,
} from "../ports/file-watcher-control";

const watcherInput = z.object({ repoPath: z.string() });

const getControl = (container: ServiceResolver) =>
  container.get<HostFileWatcherControl>(FILE_WATCHER_CONTROL);

export const fileWatcherRouter = router({
  start: publicProcedure
    .input(watcherInput)
    .mutation(({ ctx, input }) =>
      getControl(ctx.container).startWatching(input.repoPath),
    ),

  stop: publicProcedure
    .input(watcherInput)
    .mutation(({ ctx, input }) =>
      getControl(ctx.container).stopWatching(input.repoPath),
    ),
});
