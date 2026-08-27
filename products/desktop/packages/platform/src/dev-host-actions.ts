export interface IDevHostActions {
  openPath(path: string): Promise<void>;
  reloadAllWindows(): void;
  relaunch(): void;
  crash(): void;
}

export const DEV_HOST_ACTIONS_SERVICE = Symbol.for(
  "posthog.platform.devHostActions",
);
