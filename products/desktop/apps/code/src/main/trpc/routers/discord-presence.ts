import { z } from "zod";
import { container } from "../../di/container";
import { DISCORD_PRESENCE_SERVICE } from "../../di/tokens";
import {
  DiscordPresenceServiceEvent,
  discordPresenceStateSchema,
  presenceIntentSchema,
} from "../../services/discord-presence/schemas";
import type { DiscordPresenceService } from "../../services/discord-presence/service";
import { publicProcedure, router } from "../trpc";

const getService = () =>
  container.get<DiscordPresenceService>(DISCORD_PRESENCE_SERVICE);

export const discordPresenceRouter = router({
  getState: publicProcedure
    .output(discordPresenceStateSchema)
    .query(() => getService().getState()),

  setEnabled: publicProcedure
    .input(z.object({ enabled: z.boolean() }))
    .mutation(({ input }) => {
      getService().setEnabled(input.enabled);
    }),

  setShowTaskTitle: publicProcedure
    .input(z.object({ value: z.boolean() }))
    .mutation(({ input }) => {
      getService().setShowTaskTitle(input.value);
    }),

  setShowRepoName: publicProcedure
    .input(z.object({ value: z.boolean() }))
    .mutation(({ input }) => {
      getService().setShowRepoName(input.value);
    }),

  setActivity: publicProcedure
    .input(presenceIntentSchema)
    .mutation(({ input }) => {
      getService().setActivity(input);
    }),

  onStatusChanged: publicProcedure.subscription(async function* (opts) {
    const service = getService();
    for await (const data of service.toIterable(
      DiscordPresenceServiceEvent.StatusChanged,
      { signal: opts.signal },
    )) {
      yield data;
    }
  }),
});
