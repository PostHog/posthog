import fs from "node:fs";
import path from "node:path";
import v8 from "node:v8";
import type { WatchdogConfig } from "@main/watchdog/config";
import { buildReportId, type WatchdogStore } from "@main/watchdog/store";
import type {
  MemorySample,
  WatchdogReport,
  WatchdogTrigger,
} from "@main/watchdog/types";

const fsPromises = fs.promises;

const REPORT_FILE = "report.json";
const BREADCRUMB_COPY = "breadcrumbs.jsonl";
const BREADCRUMB_TAIL_LINES = 500;

const NOTES = [
  "totalRssBytes sums per-process RSS. Shared pages are counted once per process, so the real footprint is lower than the sum.",
  "Agent CLI processes run outside Electron and cannot be heap-snapshotted from the main process. Attach a Node inspector to their pid instead.",
  "Breadcrumbs are appended every sample, so the tail below survives a SIGKILL or force quit that this report would not.",
];

export interface WriteReportOptions {
  store: WatchdogStore;
  config: WatchdogConfig;
  trigger: WatchdogTrigger;
  detail?: string;
  sample: MemorySample | null;
  history: MemorySample[];
  context?: Record<string, unknown>;
  appInfo: Record<string, unknown>;
  /** Provided by the host; absent when no live renderer can be snapshotted. */
  takeRendererHeapSnapshot?: (filePath: string) => Promise<string>;
  onError: (message: string, error: unknown) => void;
}

/**
 * Writes everything we know about the current moment into a self-contained
 * report directory: the triggering sample, the samples leading up to it, V8
 * heap statistics, and — when enabled — real heap snapshots.
 */
export async function writeReport(
  options: WriteReportOptions,
): Promise<WatchdogReport> {
  const { store, config, trigger, detail, sample, history, onError } = options;
  const at = new Date();
  const id = buildReportId(at, trigger);
  const directory = await store.createReportDirectory(id);
  const files: string[] = [REPORT_FILE];

  const breadcrumbs = await store.readBreadcrumbTail(BREADCRUMB_TAIL_LINES);
  if (breadcrumbs.length > 0) {
    await fsPromises.writeFile(
      path.join(directory, BREADCRUMB_COPY),
      `${breadcrumbs.join("\n")}\n`,
      "utf-8",
    );
    files.push(BREADCRUMB_COPY);
  }

  if (config.heapSnapshots) {
    const mainSnapshot = `main-${process.pid}.heapsnapshot`;
    try {
      // Synchronous and roughly as large as the heap, which is exactly why this
      // is opt-in via POSTHOG_CODE_WATCHDOG_HEAP_SNAPSHOTS.
      v8.writeHeapSnapshot(path.join(directory, mainSnapshot));
      files.push(mainSnapshot);
    } catch (error) {
      onError("Failed to write main heap snapshot", error);
    }

    if (options.takeRendererHeapSnapshot) {
      try {
        files.push(await options.takeRendererHeapSnapshot(directory));
      } catch (error) {
        onError("Failed to write renderer heap snapshot", error);
      }
    }
  }

  const report = {
    id,
    trigger,
    detail,
    at: at.toISOString(),
    app: options.appInfo,
    config,
    context: options.context,
    sample,
    history,
    v8: {
      heapStatistics: v8.getHeapStatistics(),
      heapSpaceStatistics: v8.getHeapSpaceStatistics(),
    },
    notes: NOTES,
  };

  await fsPromises.writeFile(
    path.join(directory, REPORT_FILE),
    JSON.stringify(report, null, 2),
    "utf-8",
  );

  const summary: WatchdogReport = {
    id,
    directory,
    trigger,
    detail,
    at: at.toISOString(),
    totalRssBytes: sample?.totalRssBytes ?? 0,
    thresholdBytes: config.thresholdBytes,
    files,
  };

  await store.writeReportSummary(directory, summary);

  return summary;
}
