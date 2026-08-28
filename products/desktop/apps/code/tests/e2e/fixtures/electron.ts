import { existsSync, mkdirSync, mkdtempSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  test as base,
  type ElectronApplication,
  _electron as electron,
  type Page,
} from "@playwright/test";

function getAppPath(): string {
  const outDir = path.join(__dirname, "../../../out");
  const requestedArch = process.env.E2E_APP_ARCH;

  if (process.platform === "darwin") {
    const arm64Path = path.join(
      outDir,
      "mac-arm64/PostHog.app/Contents/MacOS/PostHog",
    );
    const x64Path = path.join(outDir, "mac/PostHog.app/Contents/MacOS/PostHog");

    if (requestedArch === "arm64") {
      if (existsSync(arm64Path)) return arm64Path;
      throw new Error(`No mac-arm64 packaged app found at ${arm64Path}.`);
    }

    if (requestedArch === "x64") {
      if (existsSync(x64Path)) return x64Path;
      throw new Error(`No mac x64 packaged app found at ${x64Path}.`);
    }

    if (existsSync(arm64Path)) return arm64Path;
    if (existsSync(x64Path)) return x64Path;

    throw new Error(
      `No packaged app found in ${outDir}. Run 'pnpm --filter code package' first.`,
    );
  }

  if (process.platform === "win32") {
    const winPath = path.join(outDir, "win-unpacked/PostHog.exe");
    if (existsSync(winPath)) return winPath;

    throw new Error(
      `No packaged app found in ${outDir}. Run 'pnpm --filter code package' first.`,
    );
  }

  if (process.platform === "linux") {
    const linuxPath = path.join(outDir, "linux-unpacked/PostHog");
    if (existsSync(linuxPath)) return linuxPath;

    throw new Error(
      `No packaged app found in ${outDir}. Run 'pnpm --filter code package' first.`,
    );
  }

  throw new Error(`Unsupported platform: ${process.platform}`);
}

type ElectronFixtures = {
  electronApp: ElectronApplication;
  window: Page;
};

export const test = base.extend<ElectronFixtures>({
  // biome-ignore lint/correctness/noEmptyPattern: Playwright fixture requires empty destructuring
  electronApp: async ({}, use) => {
    const appPath = getAppPath();
    const e2eHome = mkdtempSync(path.join(os.tmpdir(), "posthog-code-e2e-"));
    const e2eAppData = path.join(e2eHome, "app-data");
    const e2eUserData = path.join(e2eHome, "user-data");
    mkdirSync(e2eUserData, { recursive: true });
    let electronApp: ElectronApplication | undefined;

    try {
      electronApp = await electron.launch({
        executablePath: appPath,
        args: [],
        env: {
          ...process.env,
          APPDATA: e2eAppData,
          ELECTRON_DISABLE_GPU: "1",
          HOME: e2eHome,
          LOCALAPPDATA: e2eAppData,
          POSTHOG_E2E_USER_DATA_DIR: e2eUserData,
          USERPROFILE: e2eHome,
          XDG_CONFIG_HOME: e2eAppData,
        },
      });

      await use(electronApp);
    } finally {
      await electronApp?.close();
      rmSync(e2eHome, { recursive: true, force: true });
    }
  },

  window: async ({ electronApp }, use) => {
    const window = await electronApp.firstWindow();
    await window.waitForLoadState("domcontentloaded");
    await use(window);
  },
});

export { expect } from "@playwright/test";
