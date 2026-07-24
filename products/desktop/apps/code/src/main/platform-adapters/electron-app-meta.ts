import type { IAppMeta } from "@posthog/platform/app-meta";
import { app } from "electron";
import { injectable } from "inversify";

@injectable()
export class ElectronAppMeta implements IAppMeta {
  public get version(): string {
    return app.getVersion();
  }

  public get isProduction(): boolean {
    return app.isPackaged;
  }

  public get platform(): string {
    return process.platform;
  }

  public get arch(): string {
    return process.arch;
  }
}
