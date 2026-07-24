import Store from "electron-store";
import { getUserDataDir } from "../utils/env";

interface UsageThresholdStoreSchema {
  // Map of dedupe-keys ⇒ ISO timestamp anchor at which the threshold was
  // first fired. Stored so we don't re-toast after relaunch within the same
  // billing window. Anchored entries with a past anchor are pruned on boot.
  thresholdsSeen: Record<string, string>;
}

const store = new Store<UsageThresholdStoreSchema>({
  name: "usage-monitor",
  cwd: getUserDataDir(),
  defaults: {
    thresholdsSeen: {},
  },
});

/**
 * Electron-store-backed persistence for the usage-monitor threshold dedup
 * state. Implements the host-side slice of `@posthog/core/usage`'s `UsageHost`
 * port so core never touches electron-store.
 */
export const electronUsageThresholdStore = {
  getThresholdsSeen(): Record<string, string> {
    return store.get("thresholdsSeen", {});
  },
  setThresholdsSeen(value: Record<string, string>): void {
    store.set("thresholdsSeen", value);
  },
};
