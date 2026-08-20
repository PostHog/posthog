/** Why a capture happened. */
export type WatchdogTrigger =
  | "threshold"
  | "manual"
  | "render-process-gone"
  | "child-process-gone"
  | "uncaught-exception"
  | "unclean-shutdown";

export type ProcessOrigin = "electron" | "descendant";

export interface ProcessSample {
  pid: number;
  ppid?: number;
  origin: ProcessOrigin;
  /** Electron's own process type, e.g. "Browser", "Tab", "GPU", "Utility". */
  electronType?: string;
  label: string;
  rssBytes: number;
  cpuPercent: number;
}

export interface MemorySample {
  at: string;
  /** Sum of resident memory across every process in the tree. */
  totalRssBytes: number;
  electronRssBytes: number;
  descendantRssBytes: number;
  processCount: number;
  /** False on platforms where we cannot enumerate non-Electron children. */
  processTreeAvailable: boolean;
  main: {
    pid: number;
    rssBytes: number;
    heapUsedBytes: number;
    heapTotalBytes: number;
    externalBytes: number;
    arrayBuffersBytes: number;
  };
  system: {
    totalBytes: number;
    freeBytes: number;
    loadAverage: number[];
  };
  processes: ProcessSample[];
}

export interface WatchdogReport {
  id: string;
  directory: string;
  trigger: WatchdogTrigger;
  detail?: string;
  at: string;
  totalRssBytes: number;
  thresholdBytes: number;
  files: string[];
}
