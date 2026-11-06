import { UPDATES_SERVICE } from "@posthog/core/updates/identifiers";
import {
  checkForUpdatesOutput,
  installUpdateOutput,
  isEnabledOutput,
  UpdatesEvent,
  type UpdatesEvents,
  updatesStatusOutput,
} from "@posthog/core/updates/schemas";
import type { UpdatesService } from "@posthog/core/updates/updates";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import { z } from "zod";

function subscribe<K extends keyof UpdatesEvents>(event: K) {
  return publicProcedure.subscription(async function* ({ ctx, signal }) {
    const service = ctx.container.get<UpdatesService>(UPDATES_SERVICE);
    const iterable = service.toIterable(event, { signal });
    for await (const data of iterable) {
      yield data;
    }
  });
}

export const updatesRouter = router({
  isEnabled: publicProcedure.output(isEnabledOutput).query(({ ctx }) => {
    const service = ctx.container.get<UpdatesService>(UPDATES_SERVICE);
    return { enabled: service.isEnabled };
  }),

  check: publicProcedure.output(checkForUpdatesOutput).mutation(({ ctx }) => {
    const service = ctx.container.get<UpdatesService>(UPDATES_SERVICE);
    return service.checkForUpdates();
  }),

  getStatus: publicProcedure.output(updatesStatusOutput).query(({ ctx }) => {
    const service = ctx.container.get<UpdatesService>(UPDATES_SERVICE);
    return service.getStatus();
  }),

  install: publicProcedure.output(installUpdateOutput).mutation(({ ctx }) => {
    const service = ctx.container.get<UpdatesService>(UPDATES_SERVICE);
    return service.installUpdate();
  }),

  download: publicProcedure.mutation(({ ctx }) => {
    ctx.container.get<UpdatesService>(UPDATES_SERVICE).requestDownload();
  }),

  setAutoDownload: publicProcedure
    .input(z.object({ enabled: z.boolean() }))
    .mutation(({ ctx, input }) => {
      ctx.container
        .get<UpdatesService>(UPDATES_SERVICE)
        .setAutoDownloadEnabled(input.enabled);
    }),

  onReady: subscribe(UpdatesEvent.Ready),
  onStatus: subscribe(UpdatesEvent.Status),
  onCheckFromMenu: subscribe(UpdatesEvent.CheckFromMenu),
});
