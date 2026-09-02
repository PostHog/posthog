export interface FileWatcherClient {
  start(repoPath: string): Promise<void>;
  stop(repoPath: string): Promise<void>;
}

export const FILE_WATCHER_CLIENT = Symbol.for("posthog.ui.fileWatcher.client");
