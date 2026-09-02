export interface IUrlLauncher {
  launch(url: string): Promise<void>;
}

export const URL_LAUNCHER_SERVICE = Symbol.for("posthog.platform.urlLauncher");
