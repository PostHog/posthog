import { container } from "../../di/container";
import { MISSION_CONTROL_SERVICE } from "../../di/tokens";
import {
  MissionControlServiceEvent,
  missionControlStateSchema,
} from "../../services/mission-control/schemas";
import type { MissionControlService } from "../../services/mission-control/service";
import { publicProcedure, router } from "../trpc";

const getService = () =>
  container.get<MissionControlService>(MISSION_CONTROL_SERVICE);

export const missionControlRouter = router({
  getState: publicProcedure
    .output(missionControlStateSchema)
    .query(() => getService().getState()),

  onStateChanged: publicProcedure.subscription(async function* (opts) {
    const service = getService();
    for await (const data of service.toIterable(
      MissionControlServiceEvent.StateChanged,
      { signal: opts.signal },
    )) {
      yield data;
    }
  }),
});
