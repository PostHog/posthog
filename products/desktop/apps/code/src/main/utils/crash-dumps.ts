import { readdirSync, statSync, unlinkSync } from "node:fs";
import path from "node:path";
import { logger } from "./logger";

const log = logger.scope("crash-dumps");

export interface CrashDump {
  filePath: string;
  fileName: string;
  sizeBytes: number;
  writtenAtMs: number;
}

// Crashpad's database layout is per platform: the macOS and Linux databases
// move a finished dump into `pending`, the Windows one keeps every report in
// `reports`. Neither holds `new`, where a dump still being written lives.
const REPORT_DIRECTORIES = ["pending", "reports"];

// A native crash writes a minidump that nothing uploads, so dumps accumulate.
// An install that already holds a backlog must not turn one launch into a burst
// of events, so only the newest few are reported and the rest are pruned.
const MAX_REPORTED_DUMPS = 5;

function listDumpsInDirectory(reportDir: string): CrashDump[] {
  let entries: string[];
  try {
    entries = readdirSync(reportDir);
  } catch (error) {
    // No directory means this is not the layout crashpad uses here, or it has
    // never written a dump. Anything else hides dumps, so it leaves a trace.
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
      log.warn("Failed to read a crash dump directory", { reportDir, error });
    }
    return [];
  }
  const dumps: CrashDump[] = [];
  for (const fileName of entries) {
    if (!fileName.endsWith(".dmp")) continue;
    const filePath = path.join(reportDir, fileName);
    try {
      const stats = statSync(filePath);
      dumps.push({
        filePath,
        fileName,
        sizeBytes: stats.size,
        writtenAtMs: stats.mtimeMs,
      });
    } catch (error) {
      log.warn("Failed to read a crash dump", { filePath, error });
    }
  }
  return dumps;
}

/** Every dump crashpad has finished writing under `crashDumpsDir`, newest first. */
export function listCrashDumps(crashDumpsDir: string): CrashDump[] {
  return REPORT_DIRECTORIES.flatMap((name) =>
    listDumpsInDirectory(path.join(crashDumpsDir, name)),
  ).sort((a, b) => b.writtenAtMs - a.writtenAtMs);
}

export interface CrashDumpReport {
  found: number;
  reported: number;
  pruned: number;
}

/**
 * Turn the minidumps left by crashpad into exceptions, then delete them.
 *
 * A native crash never reaches the JavaScript crash handlers, so the dump on
 * disk is its only trace. The dump itself stays unread, and it does not say
 * which process faulted: crashpad's database covers every Chromium process, so
 * a renderer or GPU fault lands here too, beside the `render-process-gone` and
 * `child-process-gone` event its own handler reports. The event carries that a
 * native crash happened and when, not where in the binary.
 */
export function reportCrashDumps(
  crashDumpsDir: string,
  captureException: (error: Error, properties: Record<string, unknown>) => void,
): CrashDumpReport {
  const dumps = listCrashDumps(crashDumpsDir);
  let reported = 0;
  let pruned = 0;
  for (const [index, dump] of dumps.entries()) {
    if (index < MAX_REPORTED_DUMPS) {
      captureException(new Error("Native crash dump from a previous run"), {
        source: "main",
        type: "native-crash",
        dumpFileName: dump.fileName,
        dumpWrittenAt: new Date(dump.writtenAtMs).toISOString(),
        dumpSizeBytes: String(dump.sizeBytes),
        dumpCount: String(dumps.length),
        // Ingestion rejects the whole property bag if this is not a string,
        // which leaves the event with no issue at all.
        $exception_fingerprint: `native-crash:${process.platform}`,
      });
      reported += 1;
    }
    try {
      unlinkSync(dump.filePath);
      pruned += 1;
    } catch {}
  }
  return { found: dumps.length, reported, pruned };
}
