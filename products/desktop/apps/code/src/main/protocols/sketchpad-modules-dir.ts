import { join } from "node:path";
import { app } from "electron";

export function sketchpadModulesResourcesDir(): string {
  return app.isPackaged
    ? process.resourcesPath
    : join(app.getAppPath(), "resources");
}
