import { container } from "../../di/container";
import { MISSION_CONTROL_SERVICE } from "../../di/tokens";
import type { MissionControlService } from "../../platform-adapters/electron-mission-control";
import { MissionControlServiceEvent } from "../../services/mission-control/schemas";
import { publicProcedure, router } from "../trpc";

export const missionControlRouter = router({
  onStateChanged: publicProcedure.subscription(async function* (opts) {
    const service = container.get<MissionControlService>(
      MISSION_CONTROL_SERVICE,
    );
    for await (const data of service.toIterable(
      MissionControlServiceEvent.StateChanged,
      { signal: opts.signal },
    )) {
      yield data;
    }
  }),
});
