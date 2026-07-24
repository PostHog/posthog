import type { IClipboard } from "@posthog/platform/clipboard";
import { clipboard } from "electron";
import { injectable } from "inversify";

@injectable()
export class ElectronClipboard implements IClipboard {
  public async writeText(text: string): Promise<void> {
    clipboard.writeText(text);
  }
}
