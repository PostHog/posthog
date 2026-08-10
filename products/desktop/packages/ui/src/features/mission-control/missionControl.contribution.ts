import type { Contribution } from "@posthog/di/contribution";
import { inject, injectable } from "inversify";
import {
  MISSION_CONTROL_CLIENT,
  type MissionControlClient,
} from "./identifiers";
import { useMissionControlStore } from "./missionControlStore";

/**
 * Mirrors the host's Mission Control state into the UI store. Subscribed at boot
 * rather than from the overlay component, so entering Mission Control does not
 * also wait on a mount.
 *
 * No initial state is fetched. The store starts hidden, which is right except for
 * a renderer that reloads mid-gesture, and the next transition corrects that.
 */
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
