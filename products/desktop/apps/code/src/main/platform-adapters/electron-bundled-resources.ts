import path from "node:path";
import type { IBundledResources } from "@posthog/platform/bundled-resources";
import { app } from "electron";
import { injectable } from "inversify";

@injectable()
export class ElectronBundledResources implements IBundledResources {
  public resolve(relativePath: string): string {
    const base = app.isPackaged
      ? `${app.getAppPath()}.unpacked`
      : app.getAppPath();
    return path.join(base, relativePath);
  }
}
