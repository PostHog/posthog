import { execFile } from "node:child_process";
import path from "node:path";
import type { IFileIcon } from "@posthog/platform/file-icon";
import { app } from "electron";
import { injectable } from "inversify";

const FILE_ICON_MAX_BUFFER_BYTES = 100 * 1024 * 1024;

export function resolveMacFileIconBinary(
  appPath: string,
  isPackaged: boolean,
  modulePath: string,
): string {
  const resolvedModulePath = isPackaged
    ? path.join(`${appPath}.unpacked`, "node_modules", "file-icon", "index.js")
    : modulePath;
  return path.join(path.dirname(resolvedModulePath), "file-icon");
}

@injectable()
export class ElectronFileIcon implements IFileIcon {
  public async getAsDataUrl(filePath: string): Promise<string | null> {
    try {
      if (process.platform === "darwin") {
        const buffer = await this.getMacFileIcon(filePath);
        const base64 = buffer.toString("base64");
        return `data:image/png;base64,${base64}`;
      }

      const icon = await app.getFileIcon(filePath, { size: "normal" });
      const base64 = icon.toPNG().toString("base64");
      return `data:image/png;base64,${base64}`;
    } catch {
      return null;
    }
  }

  private getMacFileIcon(filePath: string): Promise<Buffer> {
    const binaryPath = resolveMacFileIconBinary(
      app.getAppPath(),
      app.isPackaged,
      require.resolve("file-icon"),
    );
    const input = JSON.stringify([{ appOrPID: filePath, size: 64 }]);

    return new Promise((resolve, reject) => {
      execFile(
        binaryPath,
        [input],
        { encoding: "buffer", maxBuffer: FILE_ICON_MAX_BUFFER_BYTES },
        (error, stdout) => {
          if (error) {
            reject(error);
            return;
          }
          resolve(Buffer.from(stdout));
        },
      );
    });
  }
}
