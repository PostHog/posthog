import {
  type PlatformStatus,
  platformStatusStore,
  UNKNOWN_PLATFORM_STATUS,
} from "@posthog/core/platform-status/platformStatusStore";
import type { Contribution } from "@posthog/di/contribution";
import { inject, injectable } from "inversify";
import { useAuthStore } from "../auth/store";
import {
  PLATFORM_STATUS_CLIENT,
  type PlatformStatusClient,
} from "./platformStatusClient";

const REFRESH_INTERVAL_MS = 5 * 60_000;

@injectable()
export class PlatformStatusContribution implements Contribution {
  private refreshTimeout: ReturnType<typeof setTimeout> | null = null;
  private region: "us" | "eu" | "dev" | null = null;

  constructor(
    @inject(PLATFORM_STATUS_CLIENT)
    private readonly client: PlatformStatusClient,
  ) {}

  start(): void {
    this.region = useAuthStore.getState().authState.cloudRegion;
    this.refresh();

    useAuthStore.subscribe((state) => {
      const nextRegion = state.authState.cloudRegion;
      if (nextRegion !== this.region) {
        this.region = nextRegion;
        this.refresh();
      }
    });

    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") {
        this.refresh();
      }
    });
  }

  private refresh(): void {
    if (this.refreshTimeout) {
      clearTimeout(this.refreshTimeout);
      this.refreshTimeout = null;
    }

    const region = this.region;
    if (region) {
      const setStatusIfCurrent = (status: PlatformStatus) => {
        if (this.region === region) {
          platformStatusStore.getState().setStatus(status);
        }
      };
      void this.client
        .getStatus(region)
        .then(setStatusIfCurrent)
        .catch(() => setStatusIfCurrent(UNKNOWN_PLATFORM_STATUS));
    } else {
      platformStatusStore.getState().setStatus(UNKNOWN_PLATFORM_STATUS);
    }

    this.refreshTimeout = setTimeout(() => this.refresh(), REFRESH_INTERVAL_MS);
  }
}
