import type { ITaskPreviewSessions } from "@posthog/platform/task-browser";
import { injectable } from "inversify";
import { authorizePartitionPreview } from "../electron-task-preview";

@injectable()
export class ElectronTaskPreviewSessions implements ITaskPreviewSessions {
  authorize(url: string): Promise<string | null> {
    return authorizePartitionPreview(url);
  }
}
