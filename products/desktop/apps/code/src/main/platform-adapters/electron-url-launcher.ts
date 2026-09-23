import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { promisify } from "node:util";
import type { IUrlLauncher } from "@posthog/platform/url-launcher";
import { shell } from "electron";
import { injectable } from "inversify";

const execFileAsync = promisify(execFile);
const CHROME_REMOTE_DEBUGGING_URL = "chrome://inspect/#remote-debugging";

function findWindowsChrome(): string | null {
  const installationRoots = [
    process.env.ProgramFiles,
    process.env["ProgramFiles(x86)"],
    process.env.LOCALAPPDATA,
  ].filter(Boolean) as string[];

  for (const root of installationRoots) {
    const chromePath = path.join(
      root,
      "Google",
      "Chrome",
      "Application",
      "chrome.exe",
    );
    if (existsSync(chromePath)) return chromePath;
  }

  return null;
}

@injectable()
export class ElectronUrlLauncher implements IUrlLauncher {
  public async launch(url: string): Promise<void> {
    await shell.openExternal(url);
  }

  public async launchChromeRemoteDebugging(): Promise<void> {
    if (process.platform === "darwin") {
      await execFileAsync("open", [
        "-a",
        "Google Chrome",
        CHROME_REMOTE_DEBUGGING_URL,
      ]);
      return;
    }

    if (process.platform === "win32") {
      const chromePath = findWindowsChrome();
      if (!chromePath) {
        throw new Error(
          "Google Chrome is not installed in a standard location",
        );
      }
      await execFileAsync(chromePath, [CHROME_REMOTE_DEBUGGING_URL]);
      return;
    }

    throw new Error("Chrome setup is supported on macOS and Windows only");
  }
}
