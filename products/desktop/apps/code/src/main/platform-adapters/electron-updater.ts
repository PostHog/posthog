import type {
  IUpdater,
  UpdateAvailableInfo,
  UpdateDownloadProgress,
} from "@posthog/platform/updater";
import { app } from "electron";
import log from "electron-log/main";
import {
  autoUpdater,
  type ProgressInfo,
  type UpdateInfo,
} from "electron-updater";
import { injectable } from "inversify";

function normalizeReleaseNotes(
  notes: UpdateInfo["releaseNotes"],
): string | null {
  if (!notes) return null;
  if (typeof notes === "string") return notes;
  const joined = notes
    .map((n) => n.note ?? "")
    .filter((n) => n.length > 0)
    .join("\n\n");
  return joined.length > 0 ? joined : null;
}

function pickDownloadSize(files: UpdateInfo["files"]): number | null {
  if (!files?.length) return null;
  const sizes = files.map((file) => file.size ?? 0).filter((size) => size > 0);
  return sizes.length > 0 ? Math.max(...sizes) : null;
}

@injectable()
export class ElectronUpdater implements IUpdater {
  constructor() {
    autoUpdater.logger = log;
    autoUpdater.disableDifferentialDownload = true;
    // Must stay false: UpdatesService is the sole caller of download(). If true,
    // every checkForUpdates() poll re-downloads and re-stages the same build.
    autoUpdater.autoDownload = false;
    autoUpdater.autoInstallOnAppQuit = true;

    // E2E only: redirect the updater at a local feed so a packaged build can be
    // driven through a real download and install against test artifacts. The env
    // var is never set in production.
    const e2eFeedUrl = process.env.POSTHOG_E2E_UPDATE_FEED;
    if (e2eFeedUrl) {
      autoUpdater.setFeedURL({ provider: "generic", url: e2eFeedUrl });
    }
  }

  public isSupported(): boolean {
    return (
      app.isPackaged &&
      !process.env.ELECTRON_DISABLE_AUTO_UPDATE &&
      (process.platform === "darwin" || process.platform === "win32")
    );
  }

  public check(): void {
    void autoUpdater.checkForUpdates().catch(() => undefined);
  }

  // Failures surface through the "error" event; the returned promise only
  // signals settlement so the service can serialize downloads.
  public download(): Promise<void> {
    return autoUpdater.downloadUpdate().then(
      () => undefined,
      () => undefined,
    );
  }

  public quitAndInstall(): void {
    autoUpdater.quitAndInstall(false, true);
  }

  public onCheckStart(handler: () => void): () => void {
    autoUpdater.on("checking-for-update", handler);
    return () => autoUpdater.off("checking-for-update", handler);
  }

  public onUpdateAvailable(
    handler: (info: UpdateAvailableInfo) => void,
  ): () => void {
    const l = (info: UpdateInfo) =>
      handler({
        version: info.version,
        releaseNotes: normalizeReleaseNotes(info.releaseNotes),
        releaseDate: info.releaseDate,
        releaseName: info.releaseName,
        sizeBytes: pickDownloadSize(info.files),
      });
    autoUpdater.on("update-available", l);
    return () => autoUpdater.off("update-available", l);
  }

  public onDownloadProgress(
    handler: (progress: UpdateDownloadProgress) => void,
  ): () => void {
    const l = (info: ProgressInfo) =>
      handler({
        percent: info.percent,
        bytesPerSecond: info.bytesPerSecond,
        transferred: info.transferred,
        total: info.total,
      });
    autoUpdater.on("download-progress", l);
    return () => autoUpdater.off("download-progress", l);
  }

  public onUpdateDownloaded(handler: (version: string) => void): () => void {
    const l = (info: UpdateInfo) => handler(info.version);
    autoUpdater.on("update-downloaded", l);
    return () => autoUpdater.off("update-downloaded", l);
  }

  public onNoUpdate(handler: () => void): () => void {
    autoUpdater.on("update-not-available", handler);
    return () => autoUpdater.off("update-not-available", handler);
  }

  public onError(handler: (error: Error) => void): () => void {
    const l = (error: Error) => handler(error);
    autoUpdater.on("error", l);
    return () => autoUpdater.off("error", l);
  }
}
