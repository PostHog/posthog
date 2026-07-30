export interface UpdateAvailableInfo {
  version: string;
  releaseNotes: string | null;
  releaseDate?: string;
  releaseName?: string | null;
  sizeBytes?: number | null;
}

export interface UpdateDownloadProgress {
  percent: number;
  bytesPerSecond: number;
  transferred: number;
  total: number;
}

export interface IUpdater {
  isSupported(): boolean;
  check(): void;
  download(): void;
  quitAndInstall(): void;
  setAutoDownload(enabled: boolean): void;
  onCheckStart(handler: () => void): () => void;
  onUpdateAvailable(handler: (info: UpdateAvailableInfo) => void): () => void;
  onDownloadProgress(
    handler: (progress: UpdateDownloadProgress) => void,
  ): () => void;
  onUpdateDownloaded(handler: (version: string) => void): () => void;
  onNoUpdate(handler: () => void): () => void;
  onError(handler: (error: Error) => void): () => void;
}

export const UPDATER_SERVICE = Symbol.for("posthog.platform.updater");
