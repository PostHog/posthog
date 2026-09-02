export interface IPowerManager {
  onResume(handler: () => void): () => void;
  preventSleep(reason: string): () => void;
  hasBuiltInBattery(): Promise<boolean>;
}

export const POWER_MANAGER_SERVICE = Symbol.for(
  "posthog.platform.powerManager",
);
