import type { Contribution } from "@posthog/di/contribution";
import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import { inject, injectable } from "inversify";
import {
  MISSION_CONTROL_CLIENT,
  type MissionControlClient,
} from "./identifiers";
import { useMissionControlStore } from "./missionControlStore";

/**
 * Mirrors the host's Mission Control state into the UI store. Subscribed at
 * boot rather than from the overlay component: entering Mission Control is
 * already latency-sensitive, and a mount-time subscription would add a frame of
 * lag for no benefit.
 */
@injectable()
export class MissionControlContribution implements Contribution {
  private readonly log: ScopedLogger;

  constructor(
    @inject(MISSION_CONTROL_CLIENT)
    private readonly client: MissionControlClient,
    @inject(ROOT_LOGGER) logger: RootLogger,
  ) {
    this.log = logger.scope("mission-control");
  }

  start(): void {
    const { setActive } = useMissionControlStore.getState();

    this.client
      .getState()
      .then((state) => setActive(state.active))
      .catch((error: unknown) => {
        this.log.warn("Failed to read Mission Control state", { error });
      });

    this.client.onStateChanged((state) => setActive(state.active));
  }
}
