import { readdirSync, statSync, unlinkSync } from "node:fs";
import path from "node:path";
import { logger } from "./logger";

const log = logger.scope("crash-dumps");

export interface PendingCrashDump {
  filePath: string;
  fileName: string;
  sizeBytes: number;
  writtenAtMs: number;
}

// A native crash writes a minidump that nothing uploads, so dumps accumulate.
// An install that already holds a backlog must not turn one launch into a burst
// of events, so only the newest few are reported and the rest are pruned.
const MAX_REPORTED_DUMPS = 5;

/** Newest first. */
export function listPendingCrashDumps(pendingDir: string): PendingCrashDump[] {
  let entries: string[];
  try {
    entries = readdirSync(pendingDir);
  } catch (error) {
    // No directory means crashpad has never written a dump. Anything else
    // hides dumps from both callers, so it has to leave a trace.
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
      log.warn("Failed to read the pending crash dump directory", error);
    }
    return [];
  }
  const dumps: PendingCrashDump[] = [];
  for (const fileName of entries) {
    if (!fileName.endsWith(".dmp")) continue;
    const filePath = path.join(pendingDir, fileName);
    try {
      const stats = statSync(filePath);
      dumps.push({
        filePath,
        fileName,
        sizeBytes: stats.size,
        writtenAtMs: stats.mtimeMs,
      });
    } catch (error) {
      log.warn("Failed to read a pending crash dump", { fileName, error });
    }
  }
  return dumps.sort((a, b) => b.writtenAtMs - a.writtenAtMs);
}

export interface CrashDumpReport {
  found: number;
  reported: number;
  pruned: number;
}

/**
 * Turn the minidumps left by crashpad into exceptions, then delete them.
 *
 * A native main-process crash never reaches the JavaScript crash handlers, so
 * the dump on disk is the only trace of it. The dump itself stays unread: the
 * event carries which crash happened and when, not a symbolicated stack.
 */
export function reportPendingCrashDumps(
  pendingDir: string,
  captureException: (error: Error, properties: Record<string, unknown>) => void,
): CrashDumpReport {
  const dumps = listPendingCrashDumps(pendingDir);
  let reported = 0;
  let pruned = 0;
  for (const [index, dump] of dumps.entries()) {
    if (index < MAX_REPORTED_DUMPS) {
      captureException(new Error("Native crash on a previous run"), {
        source: "main",
        type: "native-crash",
        dumpFileName: dump.fileName,
        dumpWrittenAt: new Date(dump.writtenAtMs).toISOString(),
        dumpSizeBytes: String(dump.sizeBytes),
        pendingDumpCount: String(dumps.length),
        $exception_fingerprint: ["native-crash", process.platform],
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
