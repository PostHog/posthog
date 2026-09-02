import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import {
  type IPowerManager,
  POWER_MANAGER_SERVICE,
} from "@posthog/platform/power-manager";
import {
  type IWorkspaceSettings,
  WORKSPACE_SETTINGS_SERVICE,
} from "@posthog/platform/workspace-settings";
import { inject, injectable, preDestroy } from "inversify";

@injectable()
export class SleepService {
  private enabled: boolean;
  private releaseBlocker: (() => void) | null = null;
  private activeActivities = new Set<string>();
  private readonly log: ScopedLogger;

  constructor(
    @inject(POWER_MANAGER_SERVICE)
    private readonly powerManager: IPowerManager,
    @inject(WORKSPACE_SETTINGS_SERVICE)
    private readonly settings: IWorkspaceSettings,
    @inject(ROOT_LOGGER)
    rootLogger: RootLogger,
  ) {
    this.log = rootLogger.scope("sleep");
    this.enabled = this.settings.getPreventSleepWhileRunning();
  }

  setEnabled(enabled: boolean): void {
    this.log.info("setEnabled", { enabled });
    this.enabled = enabled;
    this.settings.setPreventSleepWhileRunning(enabled);
    this.updateBlocker();
  }

  getEnabled(): boolean {
    return this.enabled;
  }

  hasBuiltInBattery(): Promise<boolean> {
    return this.powerManager.hasBuiltInBattery();
  }

  acquire(activityId: string): void {
    this.activeActivities.add(activityId);
    this.updateBlocker();
  }

  release(activityId: string): void {
    this.activeActivities.delete(activityId);
    this.updateBlocker();
  }

  @preDestroy()
  cleanup(): void {
    this.stopBlocker();
  }

  private updateBlocker(): void {
    if (this.enabled && this.activeActivities.size > 0) {
      this.startBlocker();
    } else {
      this.stopBlocker();
    }
  }

  private startBlocker(): void {
    if (this.releaseBlocker) return;
    this.releaseBlocker = this.powerManager.preventSleep(
      "prevent-app-suspension",
    );
    this.log.info("Started power save blocker");
  }

  private stopBlocker(): void {
    if (!this.releaseBlocker) return;
    this.log.info("Stopping power save blocker");
    this.releaseBlocker();
    this.releaseBlocker = null;
  }
}
