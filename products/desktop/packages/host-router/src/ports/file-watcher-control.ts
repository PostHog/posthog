export const FILE_WATCHER_CONTROL = Symbol.for(
  "posthog.host.fileWatcherControl",
);

export interface HostFileWatcherControl {
  startWatching(repoPath: string): void;
  stopWatching(repoPath: string): void;
}
