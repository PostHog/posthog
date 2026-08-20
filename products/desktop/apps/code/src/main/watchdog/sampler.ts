import os from "node:os";
import {
  type OsProcess,
  readProcessTree,
  safeProcessLabel,
} from "@main/watchdog/process-tree";
import type { MemorySample, ProcessSample } from "@main/watchdog/types";
import type { AppProcessMetric } from "@posthog/platform/app-metrics";

/** Processes retained per sample, largest first. Keeps breadcrumbs bounded. */
const MAX_PROCESSES_PER_SAMPLE = 60;
const MAX_LABEL_LENGTH = 200;

function truncate(value: string): string {
  return value.length > MAX_LABEL_LENGTH
    ? `${value.slice(0, MAX_LABEL_LENGTH)}…`
    : value;
}

/**
 * Electron's metrics and the OS process tree each see half the picture:
 * `getAppMetrics()` knows the role of every Electron process but is blind to
 * the workspace-server child and the agent CLI processes under it, while `ps`
 * sees every process but not what it is. This merges them, keyed by pid.
 */
export function mergeProcesses(
  metrics: AppProcessMetric[],
  tree: OsProcess[] | null,
  fullCommandLines = false,
): ProcessSample[] {
  const byPid = new Map<number, OsProcess>(
    (tree ?? []).map((proc) => [proc.pid, proc]),
  );
  const samples = new Map<number, ProcessSample>();

  for (const metric of metrics) {
    const observed = byPid.get(metric.pid);
    samples.set(metric.pid, {
      pid: metric.pid,
      ppid: observed?.ppid,
      origin: "electron",
      electronType: metric.type,
      label: truncate(metric.name || metric.type || `pid ${metric.pid}`),
      // `workingSetSize` is reported in kilobytes.
      rssBytes:
        observed?.rssBytes ?? (metric.memory?.workingSetSize ?? 0) * 1024,
      cpuPercent: observed?.cpuPercent ?? metric.cpu?.percentCPUUsage ?? 0,
    });
  }

  for (const proc of byPid.values()) {
    if (samples.has(proc.pid)) continue;
    samples.set(proc.pid, {
      pid: proc.pid,
      ppid: proc.ppid,
      origin: "descendant",
      label: truncate(
        (fullCommandLines ? proc.command : safeProcessLabel(proc.command)) ||
          `pid ${proc.pid}`,
      ),
      rssBytes: proc.rssBytes,
      cpuPercent: proc.cpuPercent,
    });
  }

  return [...samples.values()].sort((a, b) => b.rssBytes - a.rssBytes);
}

function buildSample(
  processes: ProcessSample[],
  processTreeAvailable: boolean,
): MemorySample {
  const memoryUsage = process.memoryUsage();

  let electronRssBytes = 0;
  let descendantRssBytes = 0;
  for (const proc of processes) {
    if (proc.origin === "electron") {
      electronRssBytes += proc.rssBytes;
    } else {
      descendantRssBytes += proc.rssBytes;
    }
  }

  return {
    at: new Date().toISOString(),
    totalRssBytes: electronRssBytes + descendantRssBytes,
    electronRssBytes,
    descendantRssBytes,
    processCount: processes.length,
    processTreeAvailable,
    main: {
      pid: process.pid,
      rssBytes: memoryUsage.rss,
      heapUsedBytes: memoryUsage.heapUsed,
      heapTotalBytes: memoryUsage.heapTotal,
      externalBytes: memoryUsage.external,
      arrayBuffersBytes: memoryUsage.arrayBuffers,
    },
    system: {
      totalBytes: os.totalmem(),
      freeBytes: os.freemem(),
      loadAverage: os.loadavg(),
    },
    processes: processes.slice(0, MAX_PROCESSES_PER_SAMPLE),
  };
}

export async function collectSample(
  getAppMetrics: () => AppProcessMetric[],
  fullCommandLines = false,
): Promise<MemorySample> {
  let tree: OsProcess[] | null = null;
  try {
    tree = await readProcessTree(process.pid);
  } catch {
    // Fall back to Electron's own metrics; the report records the gap.
    tree = null;
  }

  let metrics: AppProcessMetric[] = [];
  try {
    metrics = getAppMetrics();
  } catch {
    metrics = [];
  }

  return buildSample(
    mergeProcesses(metrics, tree, fullCommandLines),
    tree !== null,
  );
}
