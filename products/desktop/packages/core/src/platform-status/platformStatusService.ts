import type { CloudRegion } from "@posthog/shared";
import { inject, injectable } from "inversify";
import {
  PLATFORM_STATUS_CLIENT,
  type PlatformStatusClient,
} from "./identifiers";
import {
  platformStatusStore,
  UNKNOWN_PLATFORM_STATUS,
} from "./platformStatusStore";

const REFRESH_INTERVAL_MS = 5 * 60_000;

@injectable()
export class PlatformStatusService {
  private refreshTimeout: ReturnType<typeof setTimeout> | null = null;
  private region: CloudRegion | null = null;

  constructor(
    @inject(PLATFORM_STATUS_CLIENT)
    private readonly client: PlatformStatusClient,
  ) {}

  setRegion(region: CloudRegion): void {
    if (region === this.region) {
      return;
    }

    this.region = region;
    this.refresh();
  }

  refreshNow(): void {
    this.refresh();
  }

  private refresh(): void {
    if (this.refreshTimeout) {
      clearTimeout(this.refreshTimeout);
      this.refreshTimeout = null;
    }

    const region = this.region;
    if (!region) {
      return;
    }

    void this.fetchStatus(region);
    this.refreshTimeout = setTimeout(() => this.refresh(), REFRESH_INTERVAL_MS);
  }

  private async fetchStatus(region: CloudRegion): Promise<void> {
    let status = UNKNOWN_PLATFORM_STATUS;
    try {
      status = await this.client.getStatus(region);
    } catch {
      status = UNKNOWN_PLATFORM_STATUS;
    }

    if (this.region === region) {
      platformStatusStore.getState().setStatus(status);
    }
  }
}
