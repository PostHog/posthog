import type {
  ITaskBrowserSettings,
  TaskBrowserSitePolicy,
} from "@posthog/platform/task-browser";
import { injectable } from "inversify";
import { settingsStore } from "../../services/settingsStore";

@injectable()
export class ElectronTaskBrowserSettings implements ITaskBrowserSettings {
  sites(): Record<string, TaskBrowserSitePolicy> {
    return settingsStore.get("browserSites", {});
  }

  setSites(sites: Record<string, TaskBrowserSitePolicy>): void {
    settingsStore.set("browserSites", sites);
  }

  fullCdpAccess(): boolean {
    return settingsStore.get("browserFullCdpAccess", false);
  }

  setFullCdpAccess(enabled: boolean): void {
    settingsStore.set("browserFullCdpAccess", enabled);
  }
}
