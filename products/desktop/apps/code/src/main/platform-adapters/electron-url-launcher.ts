import type { IUrlLauncher } from "@posthog/platform/url-launcher";
import { shell } from "electron";
import { injectable } from "inversify";
import { decorateOutboundUrl } from "../session-stitching";

@injectable()
export class ElectronUrlLauncher implements IUrlLauncher {
  public async launch(url: string): Promise<void> {
    await shell.openExternal(decorateOutboundUrl(url));
  }
}
