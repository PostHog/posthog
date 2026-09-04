import { join } from "node:path";
import { app } from "electron";

export function canvasModulesResourcesDir(): string {
  return app.isPackaged
    ? process.resourcesPath
    : join(app.getAppPath(), "resources");
}
