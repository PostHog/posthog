import type { Contribution } from "@posthog/di/contribution";
import { inject, injectable } from "inversify";
import {
  MISSION_CONTROL_CLIENT,
  type MissionControlClient,
} from "./identifiers";
import { useMissionControlStore } from "./missionControlStore";

// No initial state is fetched: the store starts hidden and the next transition
// corrects a renderer that reloaded mid-gesture.
@injectable()
export class MissionControlContribution implements Contribution {
  constructor(
    @inject(MISSION_CONTROL_CLIENT)
    private readonly client: MissionControlClient,
  ) {}

  start(): void {
    const { setActive } = useMissionControlStore.getState();
    this.client.onStateChanged((state) => setActive(state.active));
  }
}
