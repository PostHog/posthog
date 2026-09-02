import { z } from "zod";
import { container } from "../../di/container";
import { MISSION_CONTROL_SERVICE } from "../../di/tokens";
import type { MissionControlService } from "../../platform-adapters/electron-mission-control";
import { MissionControlServiceEvent } from "../../services/mission-control/schemas";
import { publicProcedure, router } from "../trpc";

const getService = () =>
  container.get<MissionControlService>(MISSION_CONTROL_SERVICE);

export const missionControlRouter = router({
  onStateChanged: publicProcedure.subscription(async function* (opts) {
    const service = getService();
    for await (const data of service.toIterable(
      MissionControlServiceEvent.StateChanged,
      { signal: opts.signal },
    )) {
      yield data;
    }
  }),
  isSupported: publicProcedure.query(() => getService().isSupported()),
  getEnabled: publicProcedure.query(() => getService().getEnabled()),
  setEnabled: publicProcedure
    .input(z.object({ enabled: z.boolean() }))
    .mutation(({ input }) => getService().setEnabled(input.enabled)),
});
