import { execFile } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { logger } from "./logger";

const log = logger.scope("linux-appimage-protocol");

// Stable basename for the desktop entry we write. Used both as the file name in
// the applications dir and as the handler id passed to `xdg-mime default`.
const DESKTOP_FILE_BASENAME = "posthog-code";
const PRODUCT_NAME = "PostHog";

/**
 * True when the current process is a Linux AppImage. AppImage runtimes export
 * `APPIMAGE` (the stable path to the .AppImage on disk) and `APPDIR` (the
 * transient mount root, e.g. /tmp/.mount_*).
 */
export function isAppImage(): boolean {
  return process.platform === "linux" && Boolean(process.env.APPIMAGE);
}

/**
 * Build the contents of a freedesktop `.desktop` entry that registers this
 * AppImage as the handler for the given URL schemes.
 *
 * Exec must point at the stable `$APPIMAGE` path (not `$APPDIR`/process.execPath,
 * which live under a per-launch /tmp mount), so the association keeps working
 * after the app exits and is relaunched.
 */
export function buildAppImageDesktopEntry(options: {
  appImagePath: string;
  schemes: string[];
  iconPath?: string;
}): string {
  const { appImagePath, schemes, iconPath } = options;
  const mimeTypes = schemes
    .map((scheme) => `x-scheme-handler/${scheme}`)
    .join(";");
  const lines = [
    "[Desktop Entry]",
    "Type=Application",
    `Name=${PRODUCT_NAME}`,
    `Exec="${appImagePath}" %U`,
    `Icon=${iconPath ?? DESKTOP_FILE_BASENAME}`,
    "Categories=Development;",
    "Terminal=false",
    `StartupWMClass=${PRODUCT_NAME}`,
    "NoDisplay=true",
    `MimeType=${mimeTypes};`,
    "",
  ];
  return lines.join("\n");
}

function runXdg(command: string, args: string[]): Promise<void> {
  return new Promise((resolve) => {
    execFile(command, args, (error) => {
      if (error) {
        // Missing xdg utilities or a headless environment shouldn't be fatal —
        // the desktop file alone is enough once a session re-reads it.
        log.warn(`${command} failed`, {
          args,
          error: error.message,
        });
      }
      resolve();
    });
  });
}

/**
 * Best-effort copy of the AppImage's icon to a stable location so the desktop
 * entry can reference it after the AppImage's /tmp mount goes away. Returns the
 * stable absolute path, or undefined if no icon could be staged.
 */
function stageAppImageIcon(): string | undefined {
  const appDir = process.env.APPDIR;
  if (!appDir) return undefined;

  const candidates = [
    path.join(appDir, `${DESKTOP_FILE_BASENAME}.png`),
    path.join(
      appDir,
      "usr/share/icons/hicolor/512x512/apps",
      `${DESKTOP_FILE_BASENAME}.png`,
    ),
    path.join(appDir, ".DirIcon"),
  ];
  const source = candidates.find((candidate) => existsSync(candidate));
  if (!source) return undefined;

  try {
    const iconDir = path.join(os.homedir(), ".local/share/icons");
    mkdirSync(iconDir, { recursive: true });
    const destination = path.join(iconDir, `${DESKTOP_FILE_BASENAME}.png`);
    copyFileSync(source, destination);
    return destination;
  } catch (error) {
    log.warn("Failed to stage AppImage icon", {
      error: error instanceof Error ? error.message : String(error),
    });
    return undefined;
  }
}

/**
 * Register URL-scheme handlers for an AppImage build.
 *
 * `app.setAsDefaultProtocolClient` is effectively a no-op for AppImages: there
 * is no installed .desktop file for xdg to point at, so the browser can't find
 * the app to hand `posthog-code://callback?...` back to after OAuth. We write a
 * desktop entry to the user applications dir (Exec → `$APPIMAGE`) and register
 * it as the default handler for each scheme, mirroring the manual
 * `xdg-mime default` a user would otherwise run.
 */
export async function registerAppImageSchemes(
  schemes: string[],
): Promise<void> {
  const appImagePath = process.env.APPIMAGE;
  if (!appImagePath) {
    return;
  }

  const applicationsDir = path.join(os.homedir(), ".local/share/applications");
  const desktopFilePath = path.join(
    applicationsDir,
    `${DESKTOP_FILE_BASENAME}.desktop`,
  );

  try {
    mkdirSync(applicationsDir, { recursive: true });
    const iconPath = stageAppImageIcon();
    writeFileSync(
      desktopFilePath,
      buildAppImageDesktopEntry({ appImagePath, schemes, iconPath }),
      "utf8",
    );
    log.info("Wrote AppImage desktop entry", {
      desktopFilePath,
      schemes,
      appImagePath,
    });
  } catch (error) {
    log.error("Failed to write AppImage desktop entry", {
      desktopFilePath,
      error: error instanceof Error ? error.message : String(error),
    });
    return;
  }

  await runXdg("update-desktop-database", [applicationsDir]);
  for (const scheme of schemes) {
    await runXdg("xdg-mime", [
      "default",
      `${DESKTOP_FILE_BASENAME}.desktop`,
      `x-scheme-handler/${scheme}`,
    ]);
  }
}
