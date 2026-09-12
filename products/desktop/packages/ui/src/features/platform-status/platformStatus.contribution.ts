import { PLATFORM_STATUS_SERVICE } from "@posthog/core/platform-status/identifiers";
import type { PlatformStatusService } from "@posthog/core/platform-status/platformStatusService";
import type { Contribution } from "@posthog/di/contribution";
import { inject, injectable } from "inversify";
import { useAuthUiStateStore } from "../auth/authUiStateStore";
import { useAuthStore } from "../auth/store";

@injectable()
export class PlatformStatusContribution implements Contribution {
  constructor(
    @inject(PLATFORM_STATUS_SERVICE)
    private readonly statusService: PlatformStatusService,
  ) {}

  start(): void {
    this.updateRegion();
    useAuthStore.subscribe(() => this.updateRegion());
    useAuthUiStateStore.subscribe(() => this.updateRegion());

    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") {
        this.statusService.refreshNow();
      }
    });
  }

  private updateRegion(): void {
    const authRegion = useAuthStore.getState().authState.cloudRegion;
    const selectedRegion = useAuthUiStateStore.getState().selectedRegion;
    this.statusService.setRegion(authRegion ?? selectedRegion ?? "us");
  }
}
