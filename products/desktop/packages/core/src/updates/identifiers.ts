export const UPDATES_SERVICE = Symbol.for("posthog.core.updatesService");

export interface IUpdateLifecycle {
  setQuittingForUpdate(): void;
  clearQuittingForUpdate(): void;
  shutdownWithoutContainer(): Promise<void>;
}

export const UPDATE_LIFECYCLE_SERVICE = Symbol.for(
  "posthog.core.updateLifecycleService",
);
